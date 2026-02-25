# Discord Bot Brain

The centralized "brain" of the Gemini Bot ecosystem.

## Architecture: The "Home Directory"
The `discord_bot` project is designed to be run from a shared "Home Directory" (e.g., `~/code/gemini`). This root directory acts as the operational base for the bot and its companion projects (like the Dashboard).

The bot expects the following files to exist in the **Home Directory** (the parent folder):
- `.env` - Environment variables (`DISCORD_BOT_TOKEN`, `DISCORD_USER_ID`)
- `.gemini_pids` - Process tracking list
- `registry.json` - Deployed project registry

The bot will generate its own outputs inside the `discord_bot/` directory:
- `bot.log` - Application stdout/stderr
- `gemini_responses.log` - The agentic thought stream
- `bot.pid` - The current active process lockfile

## Running the Bot

Always start commands from the **Home Directory**:
```bash
cd ~/code/gemini
```

### Development Mode (Foreground)
For active development. Outputs directly to the terminal and `bot.log` simultaneously. Press `Ctrl+C` to stop.
```bash
./discord_bot/bin/dev.sh
```

### Production Mode (Background Watchdog)
For persistent execution. Starts the bot in the background and auto-restarts it if it crashes.
```bash
nohup ./discord_bot/bin/watchdog.sh > discord_bot/watchdog.log 2>&1 &
echo "[$(date '+%Y-%m-%d %H:%M:%S')] $! - watchdog.sh - Starting Discord Bot Watchdog to keep the bot alive" >> .gemini_pids
```

## Management
The bot can be monitored via the Dashboard project natively hosted at `http://localhost:8000`.
