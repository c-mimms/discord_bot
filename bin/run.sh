#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/load_env.sh"
load_dotenv_file "$ROOT_DIR/.env"

# Make sure to set the DISCORD_BOT_TOKEN and DISCORD_USER_ID environment variables
# For example:
# export DISCORD_BOT_TOKEN=your_bot_token
# export DISCORD_USER_ID=your_user_id

# Make sure we are in the discord_bot directory
cd "$ROOT_DIR"

python3 -u -m src.app.bot > "$SCRIPT_DIR/../bot.log" 2>&1
