import discord
from discord import app_commands

def setup_commands(client):
    @client.tree.command(name="projects", description="List all projects and their status")
    async def projects_command(interaction: discord.Interaction):
        registry = client.load_registry()
        projects = registry.get("projects", {})
        
        if not projects:
            await interaction.response.send_message("No projects found in registry.", ephemeral=True)
            return

        embed = discord.Embed(title="Project Registry", color=discord.Color.blue())
        for key, data in projects.items():
            status_emoji = "🟢" if data.get("status") == "active" else "🔴"
            project_type = data.get('type')
            project_path = data.get('path')
            details = f"**Type:** {project_type}\n"
            if data.get('url'): 
                details += f"**URL:** {data.get('url')}\n"
            details += f"**Path:** `{project_path}`"
            embed.add_field(name=f"{status_emoji} {data.get('name', key)}", value=details, inline=False)
        
        await interaction.response.send_message(embed=embed)

    @client.tree.command(name="aws", description="Check AWS cost summary")
    async def aws_command(interaction: discord.Interaction):
        await interaction.response.send_message("🔍 Fetching latest AWS stats... check the [Dashboard](http://localhost:8000) for full details.")
