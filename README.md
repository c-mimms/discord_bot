## Overview

This project gives you a simple **Discord DM interface to the Gemini CLI**:

- You DM your bot with an idea.
- Gemini reads the full DM history (user + bot) from `discord_bot/messages.json`.
- It first responds with a **structured plan**.
- You reply with feedback or say **"build it"**.
- Gemini continues from the existing context, asking for clarification via Discord when needed, and sending summaries of what it has done.

The glue between Discord and Gemini is:

- `discord_bot/bot.py`: the **single long-lived app**. It listens for DMs, logs them to `discord_bot/messages.json`, triggers the Gemini CLI, and flushes any queued bot messages to Discord.
- `discord_bot/send_message.py`: the **discord-helper skill entrypoint**. Gemini can call this to send messages; when the unified app is running it runs in **outbox-only** mode (logs + queues), and the app delivers the message over its single Discord connection.
- `discord_bot/gemini_main.py`: legacy single-turn runner (still useful for reference); the unified app now triggers Gemini directly.

Notes:
- The message log lives at `discord_bot/messages.json` and is written by both the listener and the discord-helper sender.

## Setup

1. **Install dependencies**

   From the `gemini` directory:

   ```bash
   pip install -r discord_bot/requirements.txt
   ```

2. **Set environment variables**

   You need at least the following variables before running the bot or sending messages:

   ```bash
   export DISCORD_BOT_TOKEN="your_bot_token"
   export DISCORD_USER_ID="your_user_id"
   # Optional: override the Gemini CLI command name if it's not just `gemini`
   # export GEMINI_CLI_CMD="gemini"
   ```

   - `DISCORD_BOT_TOKEN`: from the Discord Developer Portal.
   - `DISCORD_USER_ID`: right‑click your username in Discord → **Copy User ID** (enable Developer Mode if needed).
   - `GEMINI_CLI_CMD` (optional): if you installed the Gemini CLI under a different name, set this so `gemini_main.py` can find it.

   Authentication and model selection for Gemini are handled by the CLI itself (via its own config), not by this project.

## Usage

### 1. Run the unified Discord/Gemini app

From the `gemini` directory:

```bash
./discord_bot/run.sh
```

This starts the single long-lived process `discord_bot/bot.py`. It will:

- Log all incoming DMs into `discord_bot/messages.json`.
- Trigger the **`gemini` CLI** when you send a new DM.
- Deliver any queued outgoing messages (including those created via the `discord-helper` skill using `discord_bot/send_message.py`).

### 2. Talk to the bot

1. DM your bot with an idea (e.g. *"I want a bot that summarizes my Slack channels every morning"*).
2. Gemini will:
   - Respond with a **plan**.
   - End with instructions like **"Reply with feedback or say 'build it'."**
3. Reply with:
   - Feedback to refine the plan, or
   - Something like **"build it"** to have Gemini continue executing the plan.
4. As the conversation grows, Gemini always sees the entire DM history and can:
   - Ask you focused questions when it needs a decision.
   - Send summaries of what it has done when it reaches milestones or finishes.

All conversation state lives in the DM history plus the timestamps tracked in `discord_bot/last_message_timestamp.txt`; there is no separate database.

## Dashboard

A simple web-based dashboard is available for monitoring the bot and its activities.

### Features
- **Bot Status:** Real-time PID, CPU, and RAM monitoring for the bot.
- **Process List:** Lists active Gemini CLI instances and other child processes.
- **Log Streaming:** Real-time tailing of `bot.log` and `gemini_responses.log` via WebSockets.

### How to Run
1. Install dashboard dependencies:
   ```bash
   pip install -r dashboard/requirements.txt
   ```
2. Start the dashboard:
   ```bash
   uvicorn dashboard.main:app --port 8000
   ```
3. Access the dashboard at `http://localhost:8000`.
