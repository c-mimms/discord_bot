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
        await interaction.response.defer(ephemeral=False)
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:8000/api/aws/resources") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        embed = discord.Embed(title="AWS Cost Summary", color=discord.Color.orange())
                        
                        mtd = data.get("current_mtd", 0)
                        monthly = data.get("total_monthly", 0)
                        embed.add_field(name="💰 Current MTD Cost", value=f"${mtd:.2f}", inline=True)
                        embed.add_field(name="📅 Projected Monthly", value=f"${monthly:.2f}", inline=True)
                        
                        resources = data.get("resources", [])
                        if resources:
                            res_text = ""
                            for res in resources[:5]: # Top 5 to not overflow embed
                                res_text += f"**{res['name']}** ({res['type']}): ${res['monthly_cost']:.2f}/mo\n"
                            
                            if len(resources) > 5:
                                res_text += f"*...and {len(resources) - 5} more*"
                                
                            embed.add_field(name="Active Resources", value=res_text, inline=False)
                            
                        await interaction.followup.send(embed=embed)
                    else:
                        await interaction.followup.send(f"❌ Error fetching AWS stats: Dashboard responded with status {resp.status}")
        except Exception as e:
            await interaction.followup.send(f"❌ Error connecting to Dashboard: {e}")
