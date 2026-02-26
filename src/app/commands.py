import discord
import os
import asyncio
from discord import app_commands

def setup_commands(client):
    project_group = app_commands.Group(name="project", description="Manage project lifecycle")

    @project_group.command(name="up", description="Bring a project online")
    async def project_up(interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=False)
        registry = client.load_registry()
        projects = registry.get("projects", {})
        
        project_key = None
        for key, data in projects.items():
            if key == name or data.get("name", "").lower() == name.lower():
                project_key = key
                break
        
        if not project_key:
            await interaction.followup.send(f"❌ Project '{name}' not found.")
            return

        project = projects[project_key]
        project_path = project.get("path")
        full_path = os.path.join(client.project_root, "..", project_path)
        up_script = os.path.join(full_path, "bin", "up.sh")

        if not os.path.exists(up_script):
            await interaction.followup.send(f"❌ '{project_key}' does not support standardized `bin/up.sh` script.")
            return

        try:
            process = await asyncio.create_subprocess_exec(
                "bash", up_script,
                cwd=full_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            stdout_text = stdout.decode()
            
            if process.returncode == 0:
                project["status"] = "active"
                
                # Try to find game_url in stdout
                import re
                url_match = re.search(r"game_url\s*=\s*\"([^\"]+)\"", stdout_text)
                if url_match:
                    project["url"] = url_match.group(1)
                    await interaction.followup.send(f"✅ Project '{project_key}' is now active at {project['url']}")
                else:
                    await interaction.followup.send(f"✅ Project '{project_key}' is now active.")
                
                client.save_registry(registry)
            else:
                error_msg = stderr.decode().strip() or stdout_text.strip()
                await interaction.followup.send(f"❌ Failed to bring '{project_key}' up. (Code {process.returncode})\n```{error_msg[:1500]}```")
        except Exception as e:
            await interaction.followup.send(f"❌ Error executing up script for '{project_key}': {e}")

    @project_group.command(name="down", description="Put a project in low-cost standby")
    async def project_down(interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=False)
        registry = client.load_registry()
        projects = registry.get("projects", {})
        
        project_key = None
        for key, data in projects.items():
            if key == name or data.get("name", "").lower() == name.lower():
                project_key = key
                break
        
        if not project_key:
            await interaction.followup.send(f"❌ Project '{name}' not found.")
            return

        project = projects[project_key]
        project_path = project.get("path")
        full_path = os.path.join(client.project_root, "..", project_path)
        down_script = os.path.join(full_path, "bin", "down.sh")

        if not os.path.exists(down_script):
            await interaction.followup.send(f"❌ '{project_key}' does not support standardized `bin/down.sh` script.")
            return

        try:
            process = await asyncio.create_subprocess_exec(
                "bash", down_script,
                cwd=full_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                project["status"] = "inactive"
                client.save_registry(registry)
                await interaction.followup.send(f"✅ Project '{project_key}' is now in standby.")
            else:
                error_msg = stderr.decode().strip() or stdout.decode().strip()
                await interaction.followup.send(f"❌ Failed to put '{project_key}' in standby. (Code {process.returncode})\n```{error_msg[:1500]}```")
        except Exception as e:
            await interaction.followup.send(f"❌ Error executing down script for '{project_key}': {e}")

    client.tree.add_command(project_group)

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
