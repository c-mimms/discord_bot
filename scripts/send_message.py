import asyncio
import os
import time

import discord
from dotenv import load_dotenv

load_dotenv()

if __package__ is None or __package__ == "":
    # Allow running as a script from the project root or discord_bot directory
    import sys
    # scripts/send_message.py -> one level up to discord_bot
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

from src.utils.message_log import append_message, mark_delivered

# Placeholder for the bot token
BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')

# Placeholder for your user ID
USER_ID = os.environ.get('DISCORD_USER_ID')

intents = discord.Intents.default()
client = discord.Client(intents=intents)

DISCORD_OUTBOX_ONLY = os.environ.get("DISCORD_OUTBOX_ONLY", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _chunk_for_discord(content: str, limit: int = 1900):
    # 2000 is Discord's hard limit; keep a margin for safety.
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

async def send_message(message):
    # Always log first, so failures still show up and can be retried by the main app's outbox watcher.
    log_entry = append_message(
        author="discord_bot/send_message.py",
        content=message,
        source="bot",
        timestamp=time.time(),
        delivered=False,
    )

    if DISCORD_OUTBOX_ONLY:
        return

    await client.login(BOT_TOKEN)
    try:
        user = await client.fetch_user(USER_ID)
        for chunk in _chunk_for_discord(message):
            await user.send(chunk)
        mark_delivered(log_entry["id"], delivered=True, delivered_at=time.time())
    finally:
        await client.close()

def run_send_message(message):
    if not DISCORD_OUTBOX_ONLY and (not BOT_TOKEN or not USER_ID):
        print('Please set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables.')
        return
    
    asyncio.run(send_message(message))

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        message = ' '.join(sys.argv[1:])
        run_send_message(message)
    else:
        print('Please provide a message to send.')
