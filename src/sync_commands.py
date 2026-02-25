import os
import sys
import asyncio
import discord
from dotenv import load_dotenv

# Path setup for modular imports
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.client import GeminiClient
from src.app.commands import setup_commands

env_path = os.path.join(PROJECT_ROOT, '.env')
load_dotenv(dotenv_path=env_path)

BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN')
USER_IDS = [u.strip() for u in os.environ.get('DISCORD_USER_ID', '').split(',') if u.strip()]
GUILD_ID = os.environ.get('GUILD_ID')

if not BOT_TOKEN:
    print("Please set the DISCORD_BOT_TOKEN environment variable.")
    sys.exit(1)

class SingleSyncClient(GeminiClient):
    async def setup_hook(self):
        # Setting up commands before syncing
        setup_commands(self)
        
        print("Authenticating to Discord...")
        
        print(f"Targeting Sync...")
        try:
            if self.guild_id:
                guild = discord.Object(id=self.guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f"✅ Successfully synced {len(synced)} commands to guild {self.guild_id}.")
            else:
                synced = await self.tree.sync()
                print(f"✅ Successfully synced {len(synced)} commands globally.")
                
            print("\nSync complete! Exiting...")
            await self.close()
        except discord.errors.Forbidden as e:
            print(f"\n❌ Error 403 Forbidden: {e}")
            print("\nTROUBLESHOOTING:")
            print("1. Did you invite the bot with the 'applications.commands' scope?")
            print("2. If syncing globally, it can take up to an hour to propagate.")
            print("3. If syncing to a guild, ensure the bot is actually in that server.")
            await self.close()
        except Exception as e:
            print(f"\n❌ Unexpected error during sync: {e}")
            await self.close()

def main():
    intents = discord.Intents.default()
    client = SingleSyncClient(intents=intents, user_ids=USER_IDS, project_root=PROJECT_ROOT, guild_id=GUILD_ID)
    client.run(BOT_TOKEN)

if __name__ == "__main__":
    main()
