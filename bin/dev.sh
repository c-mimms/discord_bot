#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

source "$SCRIPT_DIR/load_env.sh"
load_dotenv_file "$ROOT_DIR/.env"

echo "Starting Discord Bot in Development Mode..."
cd "$ROOT_DIR"
python3 -u -m src.app.bot 2>&1 | tee "$ROOT_DIR/bot.log"
