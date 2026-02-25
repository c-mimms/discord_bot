import asyncio
import os
import time

import discord
from dotenv import load_dotenv

load_dotenv()

if __package__ is None or __package__ == "":
    # Allow running as a script from the discord_bot directory
    import sys
    parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

from src.app.runner import run_next_turn
from src.utils.message_log import append_message, get_undelivered_bot_messages, load_messages, mark_delivered

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Try to load .env
try:
    env_path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                if "=" in line:
                    key, val = line.split("=", 1)
                    val = val.strip().strip("\"'")
                    os.environ[key] = val
except Exception as e:
    print(f"Warning: Error loading .env: {e}")

BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
USER_IDS = [u.strip() for u in os.environ.get('DISCORD_USER_ID', '').split(',') if u.strip()]

if not BOT_TOKEN or not USER_IDS:
    print("Please set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables.")
    sys.exit(1)

# Write PID for monitoring
with open(os.path.join(BASE_DIR, "bot.pid"), "w") as f:
    f.write(str(os.getpid()))

PROJECT_ROOT = os.path.dirname(BASE_DIR)
LAST_MESSAGE_TIMESTAMP_FILE = os.path.join(BASE_DIR, "last_message_timestamp.txt")
GEMINI_CLI_CMD = os.environ.get("GEMINI_CLI_CMD", "gemini")

intents = discord.Intents.default()
intents.dm_messages = True
intents.message_content = True

client = discord.Client(intents=intents)

gemini_queue: "asyncio.Queue[dict]" = asyncio.Queue()
_tasks_started = False


def _get_last_processed_timestamp() -> float:
    if os.path.exists(LAST_MESSAGE_TIMESTAMP_FILE):
        try:
            with open(LAST_MESSAGE_TIMESTAMP_FILE, "r") as f:
                return float(f.read().strip() or "0")
        except Exception:
            return 0.0
    return 0.0


def _set_last_processed_timestamp(ts: float) -> None:
    with open(LAST_MESSAGE_TIMESTAMP_FILE, "w") as f:
        f.write(str(float(ts)))


def _chunk_for_discord(content: str, limit: int = 1900):
    text = (content or "").strip()
    if not text:
        return []
    chunks = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at < 0:
            split_at = limit
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


async def _outbox_watcher():
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            undelivered = get_undelivered_bot_messages()
            if not undelivered:
                await asyncio.sleep(0.75)
                continue

            # We use the first ID as the default for DM if no target specified
            primary_user = await client.fetch_user(int(USER_IDS[0]))
            for msg in undelivered:
                # Resolve target
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
        except Exception:
            await asyncio.sleep(2.0)


async def _gemini_worker(queue: "asyncio.Queue[dict]"):
    await client.wait_until_ready()

    # Process anything outstanding on startup (e.g. bot restarted after a user DM).
    try:
        last_ts = _get_last_processed_timestamp()
        msgs = load_messages()
        latest_user = max((m for m in msgs if m.get("source") == "user"), key=lambda m: m.get("timestamp", 0), default=None)
        if latest_user and float(latest_user.get("timestamp", 0)) > float(last_ts):
            print(f"[{time.ctime()}] Found unprocessed message on startup, queueing...", flush=True)
            await queue.put({"timestamp": float(latest_user.get("timestamp", 0))})
    except Exception as e:
        print(f"[{time.ctime()}] ERROR during _gemini_worker startup check: {e}")

    while not client.is_closed():
        evt = await queue.get()
        print(f"[{time.ctime()}] _gemini_worker: Received event from queue", flush=True)
        try:
            # Coalesce bursts
            latest_ts = float(evt.get("timestamp", 0))
            while True:
                try:
                    nxt = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    latest_ts = max(latest_ts, float(nxt.get("timestamp", 0)))
                finally:
                    queue.task_done()

            already = _get_last_processed_timestamp()
            if latest_ts <= already:
                continue

            messages = load_messages()
            # Select the most recent user message that hasn't been processed yet
            candidates = [
                m for m in messages 
                if m.get("source") == "user" and float(m.get("timestamp", 0)) > already
            ]
            if not candidates:
                continue
            
            latest_user_message = max(candidates, key=lambda m: float(m.get("timestamp", 0)))
            
            # Resolve the reply target
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
                        # Public channel - create a thread
                        thread_name = f"Gemini: {latest_user_message.get('content')[:50]}..."
                        # Note: we don't have the original message object to start a thread from here,
                        # so we create a thread in the channel. (Ideally we'd use message.create_thread)
                        reply_target = await channel.create_thread(name=thread_name, type=discord.ChannelType.public_thread)
                        # Store this thread_id for subsequent bot messages in this turn
                        thread_id = reply_target.id
            except Exception as e:
                print(f"Error resolving reply target: {e}")
            
            if not reply_target:
                # Fallback to the user who sent the message if we can't find the channel
                author_name = latest_user_message.get("author", "")
                # This is tricky because the log doesn't store the user ID, just the name.
                # However, on_message logs the author. If it's a DM, it might be the only way.
                # For now, let's try to fetch by the primary user ID if all else fails.
                reply_target = await client.fetch_user(int(USER_IDS[0]))
            
            # Streaming state
            reply_accumulator = ""
            full_reply_accumulator = ""
            active_msg = None
            last_edit_time = 0
            edit_interval = 1.0 # Throttle edits to 1 per second
            last_status = ""
            
            async def sync_discord(force=False):
                nonlocal active_msg, last_edit_time, reply_accumulator
                now = time.time()
                
                # Check for manual split sequence
                split_seq = "---NEW_MESSAGE---"
                if split_seq in reply_accumulator:
                    print(f"[{time.ctime()}] Manual split requested via {split_seq}", flush=True)
                    parts = reply_accumulator.split(split_seq, 1)
                    before = parts[0].strip()
                    # The rest starts with the part after the split sequence
                    after = parts[1]
                    
                    if before or active_msg:
                        # Finalize the current message (remove transient status)
                        display_before = before or "..."
                        # We don't prepend status to finalized chunks unless it's the very first part? 
                        # Actually, keeping it is fine as long as it's reflective of that chunk's start.
                        if last_status:
                            display_before = f"_{last_status}_\n\n{display_before}"
                        
                        if active_msg:
                            await active_msg.edit(content=display_before[:1980])
                        else:
                            active_msg = await reply_target.send(display_before[:1980])
                    
                    # Reset for next message
                    active_msg = None
                    reply_accumulator = after
                    last_edit_time = 0 # Force immediate send of the 'after' content
                    # Recurse to handle any further splits in 'after' or just to send the start of 'after'
                    return await sync_discord(force=True)

                # Automatic split on length
                if len(reply_accumulator) > 1900:
                    print(f"[{time.ctime()}] Auto-splitting message (length={len(reply_accumulator)})", flush=True)
                    # Try to find a good split point (e.g. newline)
                    split_at = reply_accumulator.rfind("\n", 1500, 1900)
                    if split_at == -1:
                        split_at = 1900
                    
                    before = reply_accumulator[:split_at].strip()
                    after = reply_accumulator[split_at:]
                    
                    display_before = before
                    if last_status:
                        display_before = f"_{last_status}_\n\n{display_before}"
                    
                    if active_msg:
                        await active_msg.edit(content=display_before[:1980])
                    else:
                        active_msg = await reply_target.send(display_before[:1980])
                        
                    active_msg = None
                    reply_accumulator = after
                    last_edit_time = 0
                    return await sync_discord(force=True)

                # Standard throttled edit
                if not force and active_msg and (now - last_edit_time < edit_interval):
                    return

                display_text = reply_accumulator.strip()
                if last_status:
                    display_text = f"_{last_status}_\n\n{display_text}"
                
                if not display_text:
                    display_text = "..." 
                
                if active_msg is None:
                    active_msg = await reply_target.send(display_text[:1980])
                    last_edit_time = now
                else:
                    await active_msg.edit(content=display_text[:1980])
                    last_edit_time = now

            # Run the Gemini turn
            async for event in run_next_turn(
                latest_user_message,
                gemini_cmd=GEMINI_CLI_CMD,
                project_root=PROJECT_ROOT,
            ):
                if event.type == "status":
                    if event.content == "spawned" and event.metadata:
                        print(f"[{time.ctime()}] Gemini CLI spawned with PID: {event.metadata.get('pid')}", flush=True)
                    elif event.content == "starting":
                        # We don't set the TS until we are sure we are done or at least started
                        pass
                elif event.type == "text":
                    reply_accumulator += event.content
                    full_reply_accumulator += event.content
                    await sync_discord()
                elif event.type == "tool_use":
                    last_status = f"Running tool: {event.content}..."
                    await sync_discord()
                elif event.type == "tool_result":
                    # We don't necessarily show tool results in the message unless we want to
                    # For now just clear the status
                    last_status = ""
                    # Don't sync yet, wait for text
                elif event.type == "error":
                    last_status = f"Error: {event.content}"
                    await sync_discord()

            # Final sync
            last_status = "" # Clear final status
            await sync_discord(force=True)

            if full_reply_accumulator.strip():
                # Remove split tokens from log
                clean_content = full_reply_accumulator.replace("---NEW_MESSAGE---", "").strip()
                append_message(
                    author="gemini",
                    content=clean_content,
                    source="bot",
                    timestamp=time.time(),
                    channel_id=channel_id,
                    thread_id=thread_id,
                )
                _set_last_processed_timestamp(float(latest_user_message.get("timestamp", 0)))

        except Exception as e:
            print(f"[{time.ctime()}] ERROR in _gemini_worker loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            queue.task_done()


@client.event
async def on_ready():
    global _tasks_started
    print(f'We have logged in as {client.user}', flush=True)
    if _tasks_started:
        return
    _tasks_started = True
    
    asyncio.create_task(_outbox_watcher())
    asyncio.create_task(_gemini_worker(gemini_queue))

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if str(message.author.id) in USER_IDS:
        print(f'Message from {message.author} in {message.channel}: {message.content}')
        
        channel_id = message.channel.id
        thread_id = None
        if isinstance(message.channel, discord.Thread):
            thread_id = message.channel.id
            channel_id = message.channel.parent_id

        entry = append_message(
            author=str(message.author),
            content=message.content,
            source="user",
            timestamp=time.time(),
            channel_id=channel_id,
            thread_id=thread_id,
        )
        try:
            gemini_queue.put_nowait({"timestamp": float(entry.get("timestamp", time.time()))})
        except Exception:
            pass


def run_bot():
    if not BOT_TOKEN or not USER_IDS:
        print('Please set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables.')
        return
    # Ensure we only have a single Discord connection in the unified app.
    os.environ["DISCORD_OUTBOX_ONLY"] = "1"
    client.run(BOT_TOKEN)

if __name__ == '__main__':
    run_bot()