#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source the .env file from the project root
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  source "$ROOT_DIR/.env"
  set +a
fi

echo "Starting Discord Bot in Development Mode..."
cd "$ROOT_DIR"
python3 -u -m src.app.bot 2>&1 | tee "$ROOT_DIR/discord_bot/bot.log"
