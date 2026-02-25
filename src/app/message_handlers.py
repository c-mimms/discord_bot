import time
import discord
from src.utils.message_log import append_message

async def handle_message(client, message, user_ids):
    if message.author == client.user:
        return

    # Ignore slash commands (Interactions)
    if message.type == discord.MessageType.chat_input_command:
        return

    if str(message.author.id) in user_ids:
        # 1. Manual Sync Command
        if message.content.strip() == "!sync":
            print(f"[{time.ctime()}] Manual sync triggered by {message.author}", flush=True)
            try:
                synced = await client.tree.sync()
                await message.channel.send(f"✅ Synced {len(synced)} commands globally.")
            except discord.errors.Forbidden as e:
                print(f"[{time.ctime()}] ❌ Error 403 Forbidden during sync: {e}", flush=True)
                await message.channel.send("❌ Error: 403 Forbidden. Bot needs `applications.commands` scope.")
            except Exception as e:
                print(f"[{time.ctime()}] ❌ Error during sync: {e}", flush=True)
                await message.channel.send(f"❌ Error during sync: {e}")
            return

        # 2. Ignore other commands
        if message.content.startswith("/"):
            return

        # 3. Process as Gemini message
        print(f'Message from {message.author}: {message.content}')
        
        channel_id = message.channel.id
        thread_id = message.channel.id if isinstance(message.channel, discord.Thread) else None
        if thread_id: channel_id = message.channel.parent_id

        entry = append_message(
            author=str(message.author),
            content=message.content,
            source="user",
            timestamp=time.time(),
            channel_id=channel_id,
            thread_id=thread_id,
        )
        if client.gemini_queue:
            client.gemini_queue.put_nowait({"timestamp": float(entry.get("timestamp", time.time()))})
