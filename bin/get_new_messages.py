#!/usr/bin/env python3
"""
get_new_messages — CLI tool for the Gemini agent to check for new user messages.

Usage (agent calls this via run_command):
    python3 discord_bot/bin/get_new_messages.py

Reads DISCORD_CONTEXT_ID and DISCORD_TURN_START_TS from the environment
(already set by the bot's runner). Prints any new user messages as plain text.
Exit code: 0 always (don't interrupt the agent on failure).
"""
import os
import sys
import time

def main():
    context_id = os.environ.get("DISCORD_CONTEXT_ID", "").strip()
    turn_start = os.environ.get("DISCORD_TURN_START_TS", "").strip()

    if not context_id:
        print("(get_new_messages: no DISCORD_CONTEXT_ID set — not in a bot context)")
        return

    since_ts = float(turn_start) if turn_start else 0.0

    try:
        # Resolve project root: this script is at discord_bot/bin/get_new_messages.py
        # discord_bot/bin -> discord_bot -> repo root
        script_dir = os.path.dirname(os.path.abspath(__file__))
        discord_bot_dir = os.path.dirname(script_dir)
        sys.path.insert(0, discord_bot_dir)
        from src.db.queries import get_messages_for_context

        messages = get_messages_for_context(context_id, limit=100)
        new_msgs = [
            m for m in messages
            if m.get("source") == "user" and float(m.get("timestamp", 0)) > since_ts
        ]

        if not new_msgs:
            print(f"(no new messages since turn start)")
            return

        print(f"--- {len(new_msgs)} NEW MESSAGE(S) FROM USER ---")
        for m in new_msgs:
            ts = time.ctime(float(m.get("timestamp", 0)))
            content = (m.get("content") or "").strip()
            print(f"[{ts}] User: {content}")
        print("--- end of new messages ---")

    except Exception as e:
        print(f"(get_new_messages error: {e})")

if __name__ == "__main__":
    main()
