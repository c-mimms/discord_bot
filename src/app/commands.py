import discord
import os
import asyncio
import datetime
import re
from pathlib import Path
from discord import app_commands

def setup_commands(client):
    allowed_user_ids = {str(uid) for uid in client.user_ids}

    async def ensure_authorized(interaction: discord.Interaction) -> bool:
        user_id = str(getattr(interaction.user, "id", ""))
        if user_id in allowed_user_ids:
            return True
        if interaction.response.is_done():
            await interaction.followup.send("❌ You are not authorized to run this command.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You are not authorized to run this command.", ephemeral=True)
        return False

    def resolve_project_path(project: dict):
        project_path = (project or {}).get("path")
        if not project_path:
            return None, "missing `path` in registry entry"
        root = Path(client.project_root).resolve()
        full_path = (root / project_path).resolve()
        try:
            full_path.relative_to(root)
        except ValueError:
            return None, f"path escapes project root: `{project_path}`"
        return str(full_path), None

    project_group = app_commands.Group(name="project", description="Manage project lifecycle")

    @project_group.command(name="up", description="Bring a project online")
    async def project_up(interaction: discord.Interaction, name: str):
        if not await ensure_authorized(interaction):
            return
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
        full_path, path_error = resolve_project_path(project)
        if path_error:
            await interaction.followup.send(f"❌ Invalid project path for '{project_key}': {path_error}")
            return
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
            
            # Helper to read and log output in real-time
            async def log_stream(stream, prefix):
                output = []
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded_line = line.decode().rstrip()
                    print(f"[{project_key}] {prefix}: {decoded_line}", flush=True)
                    output.append(decoded_line)
                return "\n".join(output)

            # Gather both streams
            stdout_task = asyncio.create_task(log_stream(process.stdout, "STDOUT"))
            stderr_task = asyncio.create_task(log_stream(process.stderr, "STDERR"))
            
            await process.wait()
            stdout_text = await stdout_task
            stderr_text = await stderr_task
            
            if process.returncode == 0:
                project["status"] = "active"
                
                # Update metadata last_updated
                if "metadata" not in registry:
                    registry["metadata"] = {}
                registry["metadata"]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d")
                
                # Try to find game_url in stdout
                url_match = re.search(r"game_url\s*=\s*\"([^\"]+)\"", stdout_text)
                if url_match:
                    project["url"] = url_match.group(1)
                    await interaction.followup.send(f"✅ Project '{project_key}' is now active at {project['url']}")
                else:
                    await interaction.followup.send(f"✅ Project '{project_key}' is now active.")
                
                client.save_registry(registry)
            else:
                error_msg = stderr_text.strip() or stdout_text.strip()
                await interaction.followup.send(f"❌ Failed to bring '{project_key}' up. (Code {process.returncode})\n```{error_msg[:1500]}```")
        except Exception as e:
            await interaction.followup.send(f"❌ Error executing up script for '{project_key}': {e}")

    @project_group.command(name="down", description="Put a project in low-cost standby")
    async def project_down(interaction: discord.Interaction, name: str):
        if not await ensure_authorized(interaction):
            return
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
        full_path, path_error = resolve_project_path(project)
        if path_error:
            await interaction.followup.send(f"❌ Invalid project path for '{project_key}': {path_error}")
            return
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
            
            # Helper to read and log output in real-time
            async def log_stream(stream, prefix):
                output = []
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded_line = line.decode().rstrip()
                    print(f"[{project_key}] {prefix}: {decoded_line}", flush=True)
                    output.append(decoded_line)
                return "\n".join(output)

            # Gather both streams
            stdout_task = asyncio.create_task(log_stream(process.stdout, "STDOUT"))
            stderr_task = asyncio.create_task(log_stream(process.stderr, "STDERR"))
            
            await process.wait()
            stdout_text = await stdout_task
            stderr_text = await stderr_task
            
            if process.returncode == 0:
                project["status"] = "inactive"
                
                # Update metadata last_updated
                if "metadata" not in registry:
                    registry["metadata"] = {}
                registry["metadata"]["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d")
                
                client.save_registry(registry)
                await interaction.followup.send(f"✅ Project '{project_key}' is now in standby.")
            else:
                error_msg = stderr_text.strip() or stdout_text.strip()
                await interaction.followup.send(f"❌ Failed to put '{project_key}' in standby. (Code {process.returncode})\n```{error_msg[:1500]}```")
        except Exception as e:
            await interaction.followup.send(f"❌ Error executing down script for '{project_key}': {e}")

    client.tree.add_command(project_group)

    @client.tree.command(name="projects", description="List all projects and their status")
    async def projects_command(interaction: discord.Interaction):
        if not await ensure_authorized(interaction):
            return
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
        if not await ensure_authorized(interaction):
            return
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
