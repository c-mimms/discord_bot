import json
import asyncio
import os
import time
import discord
import sys
from dotenv import load_dotenv

# Path setup for modular imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.client import GeminiClient
from src.app.commands import setup_commands
from src.app.workers import outbox_watcher, gemini_worker
from src.app.message_handlers import handle_message

load_dotenv()

# Config
BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
USER_IDS = [u.strip() for u in os.environ.get('DISCORD_USER_ID', '').split(',') if u.strip()]
GEMINI_CLI_CMD = os.environ.get("GEMINI_CLI_CMD", "gemini")

if not BOT_TOKEN or not USER_IDS:
    print("Please set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables.")
    sys.exit(1)

# Single Instance Lock
PID_FILE = os.path.join(PROJECT_ROOT, "bot.pid")
if os.path.exists(PID_FILE):
    try:
        with open(PID_FILE, "r") as f:
            old_pid = int(f.read().strip())
        import psutil
        if psutil.pid_exists(old_pid):
            print(f"❌ Another instance of the bot is already running (PID: {old_pid}). Exiting.")
            sys.exit(0)
    except Exception:
        pass # Ignore malformed PID files and overwrite

# Write PID for monitoring at the root of discord_bot
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

LAST_MESSAGE_TIMESTAMP_FILE = os.path.join(BASE_DIR, "last_message_timestamp.txt")

# Initialization
intents = discord.Intents.default()
intents.dm_messages = True
intents.message_content = True

client = GeminiClient(intents=intents, user_ids=USER_IDS, project_root=PROJECT_ROOT)
setup_commands(client)

@client.event
async def on_ready():
    print(f'Logged in as {client.user}', flush=True)
    if client.tasks_started:
        return
    client.tasks_started = True
    
    client.gemini_queue = asyncio.Queue()
    asyncio.create_task(outbox_watcher(client, USER_IDS))
    asyncio.create_task(gemini_worker(client, client.gemini_queue, USER_IDS, 
                                      LAST_MESSAGE_TIMESTAMP_FILE, GEMINI_CLI_CMD, PROJECT_ROOT))

@client.event
async def on_message(message):
    await handle_message(client, message, USER_IDS)

def run_bot():
    os.environ["DISCORD_OUTBOX_ONLY"] = "1"
    client.run(BOT_TOKEN)

if __name__ == '__main__':
    run_bot()
