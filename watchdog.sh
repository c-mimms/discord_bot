#!/bin/bash

# discord_bot/watchdog.sh
# Ensures the Discord bot is always running.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_PID_FILE="$SCRIPT_DIR/bot.pid"
BOT_RUN_SCRIPT="$SCRIPT_DIR/run.sh"

echo "[$(date)] Starting watchdog for Discord bot..."

while true; do
  # Load environment variables dynamically on each check/restart
  if [ -f "$SCRIPT_DIR/.env" ]; then
    # Source and export all environment variables from .env
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
  fi

  RESTART=false
  
  if [ -f "$BOT_PID_FILE" ]; then
    PID=$(cat "$BOT_PID_FILE")
    if ! ps -p "$PID" > /dev/null 2>&1; then
      echo "[$(date)] Bot (PID $PID) is not running. Restarting..."
      RESTART=true
    fi
  else
    echo "[$(date)] No PID file found. Starting bot..."
    RESTART=true
  fi

  if [ "$RESTART" = true ]; then
    # Start the bot in the background
    bash "$BOT_RUN_SCRIPT" &
    NEW_PID=$!
    echo "[$(date)] Bot started with PID $NEW_PID"
    # Wait to see if it crashes immediately
    sleep 10
    
    # Health check & rollback
    if ! ps -p "$NEW_PID" > /dev/null 2>&1; then
      echo "[$(date)] Bot failed to stay alive! Rolling back uncommitted changes..."
      (cd "$SCRIPT_DIR" && git reset --hard HEAD && git clean -fd)
      
      if [ -f "$SCRIPT_DIR/.good_commit" ]; then
         GOOD_REV=$(cat "$SCRIPT_DIR/.good_commit")
         CUR_REV=$(cd "$SCRIPT_DIR" && git rev-parse HEAD)
         if [ -n "$GOOD_REV" ] && [ "$GOOD_REV" != "$CUR_REV" ]; then
            echo "[$(date)] Commit $CUR_REV is broken. Rolling back to known good commit $GOOD_REV"
            (cd "$SCRIPT_DIR" && git reset --hard "$GOOD_REV")
         fi
      fi
      # Sleep a bit to prevent a tight crash loop
      sleep 5
    fi
  else
    # If the bot is already running healthily, mark the current commit as good
    if [ -d "$SCRIPT_DIR/.git" ]; then
      (cd "$SCRIPT_DIR" && git rev-parse HEAD > .good_commit 2>/dev/null || true)
    fi
  fi

  sleep 30
done
