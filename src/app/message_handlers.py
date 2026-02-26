import json
import time
import discord
from src.db.queries import (
    insert_message,
    create_context,
    find_context_by_reply_thread,
    find_active_context_by_channel,
    add_message_to_context,
)


def _discord_message_to_payload(message: discord.Message) -> dict:
    """Serialize the parts of a Discord Message object worth keeping."""
    payload = {
        "id": str(message.id),
        "channel_id": str(message.channel.id),
        "author": {
            "id": str(message.author.id),
            "username": str(message.author),
            "bot": message.author.bot,
        },
        "content": message.content,
        "timestamp": message.created_at.isoformat() if message.created_at else None,
        "type": str(message.type),
    }

    # Thread / channel reference
    if isinstance(message.channel, discord.Thread):
        payload["thread_id"] = str(message.channel.id)
        payload["parent_channel_id"] = str(message.channel.parent_id)

    # Message reference (reply or forward)
    if message.reference:
        payload["message_reference"] = {
            "message_id": str(message.reference.message_id) if message.reference.message_id else None,
            "channel_id": str(message.reference.channel_id) if message.reference.channel_id else None,
            "guild_id": str(message.reference.guild_id) if message.reference.guild_id else None,
        }
    referenced = getattr(message, 'referenced_message', None)
    if referenced:
        payload["referenced_message"] = {
            "id": str(referenced.id),
            "content": referenced.content,
            "author": str(referenced.author),
        }

    # Mentions
    if message.mentions:
        payload["mentions"] = [{"id": str(u.id), "username": str(u)} for u in message.mentions]
    if message.channel_mentions:
        payload["channel_mentions"] = [{"id": str(c.id), "name": str(c)} for c in message.channel_mentions]
    if message.role_mentions:
        payload["role_mentions"] = [{"id": str(r.id), "name": r.name} for r in message.role_mentions]

    # Attachments
    if message.attachments:
        payload["attachments"] = [
            {"id": str(a.id), "filename": a.filename, "url": a.url, "content_type": a.content_type}
            for a in message.attachments
        ]

    # Embeds
    if message.embeds:
        payload["embeds"] = [e.to_dict() for e in message.embeds]

    # Flags, pinned, tts
    payload["pinned"] = message.pinned
    payload["tts"] = message.tts

    return payload


async def handle_message(client, message, user_ids):
    if message.author == client.user:
        return

    # Ignore slash commands (Interactions)
    if message.type == discord.MessageType.chat_input_command:
        return

    if str(message.author.id) in user_ids:
        # 1. Manual Sync Command
        if message.content.strip().startswith("!sync"):
            print(f"[{time.ctime()}] Manual sync triggered by {message.author}", flush=True)
            try:
                parts = message.content.split()
                if len(parts) > 1 and parts[1] == "guild":
                    client.tree.copy_global_to(guild=message.guild)
                    synced = await client.tree.sync(guild=message.guild)
                    await message.channel.send(f"✅ Synced {len(synced)} commands to this guild.")
                else:
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

        # 3. Determine origin
        print(f'Message from {message.author}: {message.content}')

        is_thread = isinstance(message.channel, discord.Thread)
        channel_id = message.channel.parent_id if is_thread else message.channel.id
        thread_id = message.channel.id if is_thread else None

        # 4. Store the raw message (pure append-only log)
        raw_payload = _discord_message_to_payload(message)
        msg_entry = insert_message(
            author=str(message.author),
            content=message.content,
            source="user",
            timestamp=time.time(),
            channel_id=channel_id,
            thread_id=thread_id,
            raw_discord_payload=raw_payload,
        )

        # 5. Route to a context
        #    If the message came from a thread, find the context that owns it.
        #    Otherwise, check if there's an active context for this channel (e.g. DM).
        #    If none found, create a fresh context.
        context_id = None
        if thread_id:
            context_id = find_context_by_reply_thread(thread_id)
        else:
            # Look for an active context in this channel (DMs/standard channels)
            context_id = find_active_context_by_channel(channel_id)

        if not context_id:
            context_id = create_context(reply_channel_id=channel_id, reply_thread_id=thread_id)

        # 6. Link message to context
        add_message_to_context(context_id, msg_entry["id"])

        # 7. Enqueue for processing
        if client.gemini_queue:
            client.gemini_queue.put_nowait({"context_id": context_id})
