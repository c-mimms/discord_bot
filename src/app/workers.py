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
    
    # Simple cache for User/Channel objects to reduce fetch_* calls
    cache = {}

    async def get_target(cid=None, tid=None, uid=None):
        cache_key = f"t:{tid}" if tid else (f"c:{cid}" if cid else f"u:{uid}")
        if cache_key in cache:
            return cache[cache_key]
        
        target = None
        try:
            if tid:
                target = client.get_channel(int(tid)) or await client.fetch_channel(int(tid))
            elif cid:
                target = client.get_channel(int(cid)) or await client.fetch_channel(int(cid))
            elif uid:
                target = client.get_user(int(uid)) or await client.fetch_user(int(uid))
            
            if target:
                cache[cache_key] = target
        except Exception:
            pass
        return target

    while not client.is_closed():
        try:
            undelivered = get_undelivered_bot_messages()
            if not undelivered:
                await asyncio.sleep(1.0)
                continue

            for msg in undelivered:
                msg_id = msg.get("id", "")
                target = await get_target(
                    cid=msg.get("channel_id"), 
                    tid=msg.get("thread_id"), 
                    uid=user_ids[0]
                )
                
                if not target:
                    print(f"[{time.ctime()}] [Ctx: outbox] Could not resolve target for msg {msg_id}")
                    continue

                content = (msg.get("content") or "").strip()
                if not content:
                    mark_delivered(msg_id, delivered=True, delivered_at=time.time())
                    continue

                # Chunk content to stay within Discord's 2000-char limit
                chunks = []
                remaining = content
                while len(remaining) > 1900:
                    split_at = remaining.rfind("\n", 0, 1900)
                    if split_at < 0: split_at = 1900
                    chunks.append(remaining[:split_at].rstrip())
                    remaining = remaining[split_at:].lstrip("\n")
                if remaining: chunks.append(remaining)

                print(f"[{time.ctime()}] [Ctx: outbox] Sending message to {target} ({len(chunks)} chunk(s))", flush=True)
                try:
                    for chunk in chunks:
                        await target.send(chunk)
                    mark_delivered(msg_id, delivered=True, delivered_at=time.time())
                except Exception as send_err:
                    print(f"[{time.ctime()}] [Ctx: outbox] Send error for msg {msg_id}: {send_err}")
                    mark_failed_delivery(msg_id, str(send_err))
            
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"[{time.ctime()}] [Ctx: outbox] Error in outbox_watcher: {e}")
            await asyncio.sleep(5.0)

async def check_for_missed_messages(client, user_ids):
    """Fetch recent history for active contexts and inject missing user messages."""
    print(f"[{time.ctime()}] Starting missed message catch-up...")
    from src.db.queries import get_active_contexts, insert_message, add_message_to_context, get_messages_for_context
    from src.app.message_handlers import _discord_message_to_payload

    active_ctxs = get_active_contexts(limit=10)
    for ctx in active_ctxs:
        context_id = ctx['id']
        channel_id = ctx.get('reply_thread_id') or ctx.get('reply_channel_id')
        if not channel_id:
            continue

        try:
            channel = client.get_channel(int(channel_id)) or await client.fetch_channel(int(channel_id))
            if not channel: continue

            # Get DB's view of recent messages
            db_messages = {m['id'] for m in get_messages_for_context(context_id, limit=20)}
            
            # Fetch Discord's view
            async for message in channel.history(limit=20):
                if str(message.id) in db_messages:
                    continue
                
                if not message.author.bot and str(message.author.id) in user_ids:
                    print(f"[{time.ctime()}] [Ctx: {context_id}] Catching up missed message: {message.id}")
                    
                    should_process = False
                    is_thread = isinstance(message.channel, discord.Thread)
                    if isinstance(message.channel, discord.DMChannel):
                        should_process = True
                    elif client.user in message.mentions:
                        should_process = True
                    elif is_thread:
                        from src.db.queries import find_context_by_reply_thread
                        if find_context_by_reply_thread(message.channel.id):
                            should_process = True

                    raw_payload = _discord_message_to_payload(message)
                    msg_entry = insert_message(
                        author=str(message.author),
                        content=message.content,
                        source="user",
                        timestamp=message.created_at.timestamp(),
                        channel_id=message.channel.id if not isinstance(message.channel, discord.Thread) else message.channel.parent_id,
                        thread_id=message.channel.id if isinstance(message.channel, discord.Thread) else None,
                        raw_discord_payload=raw_payload,
                    )
                    add_message_to_context(context_id, msg_entry["id"])
                    
                    if should_process:
                        if client.gemini_queue:
                            client.gemini_queue.put_nowait({"context_id": context_id})
                    else:
                        silent_msg = insert_message(
                            author="system",
                            content="",
                            source="bot",
                            timestamp=time.time(),
                            channel_id=msg_entry["channel_id"],
                            thread_id=msg_entry["thread_id"],
                            delivered=True,
                            delivered_at=time.time(),
                        )
                        add_message_to_context(context_id, silent_msg["id"])

        except Exception as e:
            print(f"[{time.ctime()}] [Ctx: {context_id}] Error in catch-up: {e}")

async def loop_monitor():
    """Monitor event loop lag."""
    print("Event loop monitor started.")
    while True:
        start = time.perf_counter()
        await asyncio.sleep(1)
        end = time.perf_counter()
        lag = (end - start) - 1
        if lag > 0.5:
            print(f"[{time.ctime()}] ⚠️ Loop LAG warning: {lag:.3f}s")

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

        has_output = False
        async for event in run_next_turn(
            latest_user_message,
            context_id=context_id,
            gemini_cmd=gemini_cmd,
            project_root=project_root,
        ):
            if event.type == "text":
                has_output = True
                reply_accumulator += event.content
                full_reply_accumulator += event.content
                await sync_discord()
            elif event.type == "tool_use":
                has_output = True
                last_status = f"Running tool: {event.content}..."
                await sync_discord()
            elif event.type == "tool_result":
                has_output = True
                last_status = ""
            elif event.type == "error":
                last_status = f"Error: {event.content}"
                await sync_discord()
                
                # If we encounter a Quota/Rate limit error, we must mark the turn as "handled"
                # so the polling loop doesn't keep retrying it forever.
                if any(x in event.content for x in ["Quota", "capacity", "429"]):
                    error_msg_content = f"⚠️ I'm currently over my rate limit or capacity ({event.content}). Please try again later."
                    bot_msg = insert_message(
                        author="gemini",
                        content=error_msg_content,
                        source="bot",
                        timestamp=time.time(),
                        channel_id=reply_channel_id,
                        thread_id=reply_thread_id,
                        delivered=True,
                        delivered_at=time.time(),
                    )
                    add_message_to_context(context_id, bot_msg["id"])
                    has_output = True # Prevent the fall-through error handling if this was the only event

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
        elif not has_output:
            # If Gemini returned NO events (e.g. CLI crashed immediately), we still need to break the loop
            print(f"[{time.ctime()}] [Ctx: {context_id}] WARNING: Gemini turn produced no output events. Marking as failed to break retry loop.")
            bot_msg = insert_message(
                author="gemini",
                content="⚠️ I encountered an internal error and couldn't generate a response.",
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
        await asyncio.sleep(15) # Longer interval

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

    asyncio.create_task(loop_monitor())
    asyncio.create_task(polling_fallback(queue))
    running_tasks = set()

    # Initial catch-up for missed messages
    # asyncio.create_task(check_for_missed_messages(client, user_ids))

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
