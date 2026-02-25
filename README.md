# Discord Bot Brain

The centralized "brain" of the Gemini Bot.

## Project Structure

- `src/`: Core Python logic
  - `app/`: Main application entry points (`bot.py`, `runner.py`, `mcp.py`)
  - `utils/`: Shared utilities (`message_log.py`)
- `bin/`: Operational bash scripts (`run.sh`, `watchdog.sh`, `send_message.sh`)
- `scripts/`: CLI tools for out-of-band communication (`send_message.py`)
- `skills/`: Source for bot skills (e.g., `discord-helper`)
- `bot.log`: Main bot execution log
- `gemini_responses.log`: Log of Gemini's thought processes and actions
- `bot.pid`: PID of the currently running bot process

## Running the Bot

Use the watchdog to ensure the bot stays alive:
```bash
bash bin/watchdog.sh
```

## Management

The bot can be monitored via the Dashboard project in the root.
