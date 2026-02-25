import os
import json
import discord
from discord import app_commands

class GeminiClient(discord.Client):
    def __init__(self, *, intents: discord.Intents, user_ids: list, project_root: str):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.user_ids = user_ids
        self.project_root = project_root
        self.gemini_queue = None # Will be set by workers
        self.tasks_started = False

    async def setup_hook(self):
        # Sync slash commands globally
        await self.tree.sync()

    def load_registry(self):
        registry_path = os.path.join(self.project_root, "registry.json")
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}
