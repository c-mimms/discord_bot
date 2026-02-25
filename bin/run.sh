#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the .env file
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

# Make sure to set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables
# For example:
# export DISCORD_BOT_TOKEN="your_bot_token"
# export DISCORD_USER_ID="your_user_id"

# Make sure we are in the discord_bot directory
cd "$SCRIPT_DIR/.."

python3 -u -m src.app.bot > "$SCRIPT_DIR/../bot.log" 2>&1
