#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/load_env.sh"
load_dotenv_file "$ROOT_DIR/.env"

# Make sure to set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables
# For example:
# export DISCORD_BOT_TOKEN=your_bot_token
# export DISCORD_USER_ID=your_user_id

python3 "$SCRIPT_DIR/../scripts/send_message.py" "$@"
