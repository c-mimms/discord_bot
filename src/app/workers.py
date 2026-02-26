import asyncio
import os
import time
import discord
from src.app.runner import run_next_turn
from src.db.queries import (
    get_undelivered_bot_messages, mark_delivered, insert_message,
    mark_failed_delivery,
    add_message_to_context,
    get_idle_contexts_with_pending_user_messages, update_context_status,
    get_latest_user_message_for_context, get_context, set_context_reply_thread,
)
from src.db.database import get_db

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
                msg_id = msg.get("id", "")
                if not content:
                    mark_delivered(msg_id, delivered=True, delivered_at=time.time())
                    continue

                # Chunk content to stay within Discord's 2000-char limit
                chunks = []
                remaining = content
                while len(remaining) > 1900:
                    split_at = remaining.rfind("\n", 0, 1900)
                    if split_at < 0:
                        split_at = 1900
                    chunks.append(remaining[:split_at].rstrip())
                    remaining = remaining[split_at:].lstrip("\n")
                if remaining:
                    chunks.append(remaining)

                print(f"[{time.ctime()}] [Ctx: outbox] Sending message to {target} ({len(chunks)} chunk(s)): {content[:50]}...", flush=True)
                try:
                    for chunk in chunks:
                        await target.send(chunk)
                    if msg_id:
                        mark_delivered(msg_id, delivered=True, delivered_at=time.time())
                except Exception as send_err:
                    print(f"[{time.ctime()}] [Ctx: outbox] Send error for msg {msg_id}: {send_err}")
                    if msg_id:
                        mark_failed_delivery(msg_id, str(send_err))
        except Exception as e:
            print(f"[{time.ctime()}] [Ctx: outbox] Error in outbox_watcher: {e}")
            await asyncio.sleep(2.0)

async def process_context(context_id: str, client, user_ids, gemini_cmd, project_root):
    try:
        latest_user_message = get_latest_user_message_for_context(context_id)
        if not latest_user_message:
            return

        # Load context to find reply target
        ctx = get_context(context_id)
        reply_thread_id = ctx.get("reply_thread_id") if ctx else None
        reply_channel_id = ctx.get("reply_channel_id") if ctx else None

        reply_target = None
        try:
            if reply_thread_id:
                # Already have a thread — reply there
                reply_target = client.get_channel(reply_thread_id) or await client.fetch_channel(reply_thread_id)
            elif reply_channel_id:
                channel = client.get_channel(reply_channel_id) or await client.fetch_channel(reply_channel_id)
                if isinstance(channel, discord.DMChannel):
                    reply_target = channel
                else:
                    # Create a thread for this conversation
                    thread_name = f"Gemini: {latest_user_message.get('content', '')[:50]}..."
                    reply_target = await channel.create_thread(
                        name=thread_name,
                        type=discord.ChannelType.public_thread,
                    )
                    # Register the new thread so future messages route here
                    set_context_reply_thread(context_id, reply_target.id)
                    reply_thread_id = reply_target.id
        except Exception as e:
            print(f"[{time.ctime()}] [Ctx: {context_id}] WARNING: Could not resolve reply target: {e}", flush=True)

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

            # Manual Split
            if "---NEW_MESSAGE---" in reply_accumulator:
                parts = reply_accumulator.split("---NEW_MESSAGE---", 1)
                before = parts[0].strip()
                after = parts[1]
                if before or active_msg:
                    display_before = before or "..."
                    if last_status:
                        display_before = f"_{last_status}_\n\n{display_before}"
                    if active_msg: await active_msg.edit(content=display_before[:1800])
                    else: active_msg = await reply_target.send(display_before[:1800])
                active_msg = None
                reply_accumulator = after
                last_edit_time = 0
                return await sync_discord(force=True)

            # Auto Split
            if len(reply_accumulator) > 1800:
                split_at = reply_accumulator.rfind("\n", 1500, 1800)
                if split_at == -1: split_at = 1800
                before = reply_accumulator[:split_at].strip()
                after = reply_accumulator[split_at:]
                display_before = before
                if last_status:
                    display_before = f"_{last_status}_\n\n{display_before}"
                if active_msg: await active_msg.edit(content=display_before[:1800])
                else: active_msg = await reply_target.send(display_before[:1800])
                active_msg = None
                reply_accumulator = after
                last_edit_time = 0
                return await sync_discord(force=True)

            now = time.time()
            if not force and active_msg and (now - last_edit_time < edit_interval):
                return

            display_text = reply_accumulator.strip() or "..."
            if last_status:
                display_text = f"_{last_status}_\n\n{display_text}"

            if active_msg is None:
                active_msg = await reply_target.send(display_text[:1800])
            else:
                await active_msg.edit(content=display_text[:1800])
            last_edit_time = now

        async for event in run_next_turn(
            latest_user_message,
            context_id=context_id,
            gemini_cmd=gemini_cmd,
            project_root=project_root,
        ):
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
            # Store bot reply as delivered (was streamed live; outbox must NOT re-send)
            bot_msg = insert_message(
                author="gemini",
                content=clean_content,
                source="bot",
                timestamp=time.time(),
                channel_id=reply_channel_id,
                thread_id=reply_thread_id,
                delivered=True,
                delivered_at=time.time(),
            )
            add_message_to_context(context_id, bot_msg["id"])

    except Exception as e:
        print(f"[{time.ctime()}] [Ctx: {context_id}] ERROR in process_context: {e}")
    finally:
        update_context_status(context_id, 'idle')

async def polling_fallback(queue):
    while True:
        try:
            contexts = get_idle_contexts_with_pending_user_messages()
            for cid in contexts:
                await queue.put({"context_id": cid})
        except Exception as e:
            print(f"Error in polling fallback: {e}")
        await asyncio.sleep(10)

async def gemini_worker(client, queue, user_ids, timestamp_file, gemini_cmd, project_root):
    print("Gemini parallel worker started.")
    await client.wait_until_ready()

    # Reset any contexts stuck in 'running' from a previous crashed process
    try:
        with get_db() as conn:
            result = conn.execute("UPDATE contexts SET status = 'idle', current_pid = NULL WHERE status = 'running'")
            if result.rowcount > 0:
                print(f"[{time.ctime()}] Reset {result.rowcount} stale 'running' context(s) to 'idle'.", flush=True)
    except Exception as e:
        print(f"[{time.ctime()}] WARNING: Could not reset stale contexts: {e}", flush=True)

    asyncio.create_task(polling_fallback(queue))
    running_tasks = set()

    while not client.is_closed():
        evt = await queue.get()
        try:
            context_id = evt.get("context_id")
            if not context_id:
                continue

            try:
                with get_db() as conn:
                    cursor = conn.execute("SELECT status FROM contexts WHERE id = ?", (context_id,))
                    row = cursor.fetchone()
                    if row and row['status'] == 'idle':
                        update_context_status(context_id, 'running', os.getpid())
                        task = asyncio.create_task(
                            process_context(context_id, client, user_ids, gemini_cmd, project_root)
                        )
                        running_tasks.add(task)
                        task.add_done_callback(running_tasks.discard)
            except Exception as e:
                print(f"DB Error checking context {context_id}: {e}")

        except Exception as e:
            print(f"[{time.ctime()}] ERROR in gemini_worker loop: {e}")
        finally:
            queue.task_done()
