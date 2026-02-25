#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Source the .env file to load the environment variables
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

# Make sure to set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables
# For example:
# export DISCORD_BOT_TOKEN="your_bot_token"
# export DISCORD_USER_ID="your_user_id"

python3 "$SCRIPT_DIR/send_message.py" "$@"
