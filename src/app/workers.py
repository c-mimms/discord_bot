import asyncio
import os
import time
import json
import discord
from src.app.runner import run_next_turn
from src.utils.message_log import append_message, get_undelivered_bot_messages, load_messages, mark_delivered

def get_last_processed_timestamp(file_path) -> float:
    if os.path.exists(file_path):
        try:
            with open(file_path, "r") as f:
                return float(f.read().strip() or "0")
        except Exception:
            return 0.0
    return 0.0

def set_last_processed_timestamp(file_path, ts: float) -> None:
    with open(file_path, "w") as f:
        f.write(str(float(ts)))

async def outbox_watcher(client, user_ids):
    print("Outbox watcher started.")
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            undelivered = get_undelivered_bot_messages()
            if not undelivered:
                await asyncio.sleep(0.75)
                continue

            primary_user = await client.fetch_user(int(user_ids[0]))
            for msg in undelivered:
                target = None
                channel_id = msg.get("channel_id")
                thread_id = msg.get("thread_id")
                
                try:
                    if thread_id:
                        target = client.get_channel(thread_id) or await client.fetch_channel(thread_id)
                    elif channel_id:
                        target = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
                    
                    if not target:
                        target = primary_user
                except Exception:
                    target = primary_user

                content = (msg.get("content") or "").strip()
                if not content:
                    mark_delivered(msg.get("id", ""), delivered=True, delivered_at=time.time())
                    continue
                
                print(f"[{time.ctime()}] Sending message to {target}: {content[:50]}...", flush=True)
                await target.send(content)
                if msg.get("id"):
                    mark_delivered(msg["id"], delivered=True, delivered_at=time.time())
        except Exception as e:
            print(f"Error in outbox_watcher: {e}")
            await asyncio.sleep(2.0)

async def gemini_worker(client, queue, user_ids, timestamp_file, gemini_cmd, project_root):
    print("Gemini worker started.")
    await client.wait_until_ready()
    try:
        last_ts = get_last_processed_timestamp(timestamp_file)
        msgs = load_messages()
        latest_user = max((m for m in msgs if m.get("source") == "user"), key=lambda m: m.get("timestamp", 0), default=None)
        if latest_user and float(latest_user.get("timestamp", 0)) > float(last_ts):
            print(f"[{time.ctime()}] Found unprocessed message on startup, queueing...", flush=True)
            await queue.put({"timestamp": float(latest_user.get("timestamp", 0))})
    except Exception as e:
        print(f"[{time.ctime()}] ERROR during gemini_worker startup check: {e}")

    while not client.is_closed():
        evt = await queue.get()
        try:
            latest_ts = float(evt.get("timestamp", 0))
            while True:
                try:
                    nxt = queue.get_nowait()
                    latest_ts = max(latest_ts, float(nxt.get("timestamp", 0)))
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break

            already = get_last_processed_timestamp(timestamp_file)
            if latest_ts <= already:
                continue

            messages = load_messages()
            candidates = [m for m in messages if m.get("source") == "user" and float(m.get("timestamp", 0)) > already]
            if not candidates: continue
            
            latest_user_message = max(candidates, key=lambda m: float(m.get("timestamp", 0)))
            channel_id = latest_user_message.get("channel_id")
            thread_id = latest_user_message.get("thread_id")
            
            reply_target = None
            try:
                if thread_id:
                    reply_target = client.get_channel(thread_id) or await client.fetch_channel(thread_id)
                elif channel_id:
                    channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
                    if isinstance(channel, discord.DMChannel):
                        reply_target = channel
                    else:
                        thread_name = f"Gemini: {latest_user_message.get('content')[:50]}..."
                        reply_target = await channel.create_thread(name=thread_name, type=discord.ChannelType.public_thread)
                        thread_id = reply_target.id
            except Exception: pass
            
            if not reply_target:
                reply_target = await client.fetch_user(int(user_ids[0]))
            
            reply_accumulator = ""
            full_reply_accumulator = ""
            active_msg = None
            last_edit_time = 0
            edit_interval = 1.0
            last_status = ""
            
            async def sync_discord(force=False):
                nonlocal active_msg, last_edit_time, reply_accumulator
                now = time.time()
                
                # Manual Split
                if "---NEW_MESSAGE---" in reply_accumulator:
                    parts = reply_accumulator.split("---NEW_MESSAGE---", 1)
                    before = parts[0].strip()
                    after = parts[1]
                    if before or active_msg:
                        display_before = before or "..."
                        if last_status: 
                            display_before = f"_{last_status}_\n\n{display_before}"
                        if active_msg: await active_msg.edit(content=display_before[:1980])
                        else: active_msg = await reply_target.send(display_before[:1980])
                    active_msg = None
                    reply_accumulator = after
                    last_edit_time = 0
                    return await sync_discord(force=True)

                # Auto Split
                if len(reply_accumulator) > 1900:
                    split_at = reply_accumulator.rfind("\n", 1500, 1900)
                    if split_at == -1: split_at = 1900
                    before = reply_accumulator[:split_at].strip()
                    after = reply_accumulator[split_at:]
                    display_before = before
                    if last_status: 
                        display_before = f"_{last_status}_\n\n{display_before}"
                    if active_msg: await active_msg.edit(content=display_before[:1980])
                    else: active_msg = await reply_target.send(display_before[:1980])
                    active_msg = None
                    reply_accumulator = after
                    last_edit_time = 0
                    return await sync_discord(force=True)

                if not force and active_msg and (now - last_edit_time < edit_interval): return

                display_text = reply_accumulator.strip() or "..."
                if last_status: 
                    display_text = f"_{last_status}_\n\n{display_text}"
                
                if active_msg is None:
                    active_msg = await reply_target.send(display_text[:1980])
                else:
                    await active_msg.edit(content=display_text[:1980])
                last_edit_time = now

            async for event in run_next_turn(latest_user_message, gemini_cmd=gemini_cmd, project_root=project_root):
                if event.type == "text":
                    reply_accumulator += event.content
                    full_reply_accumulator += event.content
                    await sync_discord()
                elif event.type == "tool_use":
                    last_status = f"Running tool: {event.content}..."
                    await sync_discord()
                elif event.type == "tool_result":
                    last_status = ""
                elif event.type == "error":
                    last_status = f"Error: {event.content}"
                    await sync_discord()

            last_status = ""
            await sync_discord(force=True)

            if full_reply_accumulator.strip():
                clean_content = full_reply_accumulator.replace("---NEW_MESSAGE---", "").strip()
                append_message(author="gemini", content=clean_content, source="bot", timestamp=time.time(),
                              channel_id=channel_id, thread_id=thread_id)
                set_last_processed_timestamp(timestamp_file, float(latest_user_message.get("timestamp", 0)))

        except Exception as e:
            print(f"[{time.ctime()}] ERROR in gemini_worker loop: {e}")
        finally:
            queue.task_done()
