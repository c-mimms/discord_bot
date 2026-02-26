import os
import json
import discord
from discord import app_commands

class GeminiClient(discord.Client):
    def __init__(self, *, intents: discord.Intents, user_ids: list, project_root: str, guild_id: str = None):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.user_ids = user_ids
        self.project_root = project_root
        self.guild_id = guild_id
        self.gemini_queue = None # Will be set by workers
        self.tasks_started = False

    async def setup_hook(self):
        print(f"Bot logged in as {self.user} (ID: {self.user.id})")
        print(f"Application ID: {self.application_id}")
        # Manual sync trigger will be used instead of auto-sync on startup

    def load_registry(self):
        registry_path = os.path.join(self.project_root, "registry.json")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_registry(self, data):
        registry_path = os.path.join(self.project_root, "registry.json")
        try:
            with open(registry_path, "w") as f:
                json.dump(data, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving registry: {e}")
            return False
