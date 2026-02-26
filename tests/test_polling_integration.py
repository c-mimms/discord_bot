#!/usr/bin/env python3
"""
Integration test: verify Gemini agent calls get_new_messages.py via run_command.

Run from repo root:
    python3 discord_bot/tests/test_polling_integration.py

Expects to complete in under 60 seconds.
Exit 0 = PASS, Exit 1 = FAIL
"""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.db.queries import create_context, insert_message, add_message_to_context

GEMINI_CMD = os.environ.get("GEMINI_CLI_CMD", "gemini")
TIMEOUT = 60

# Minimal prompt that forces a single run_command call then stops
PROMPT = (
    "You MUST use run_command to execute exactly this shell command: "
    "`python3 discord_bot/bin/get_new_messages.py` "
    "Print the output. Then say DONE and stop. Do nothing else."
)

def main():
    # Set up a DB context so the script has something to query
    ctx = create_context(reply_channel_id=0)
    msg = insert_message("user", PROMPT, "user")
    add_message_to_context(ctx, msg["id"])
    ts = str(msg["timestamp"])

    env = {
        **os.environ,
        "DISCORD_CONTEXT_ID": ctx,
        "DISCORD_TURN_START_TS": ts,
        "TERM": "dumb",
        "GEMINI_CLI_NON_INTERACTIVE": "1",
        "DISCORD_OUTBOX_ONLY": "1",
    }

    print(f"Starting Gemini CLI (timeout={TIMEOUT}s)...")
    proc = subprocess.Popen(
        [GEMINI_CMD, "--output-format", "stream-json", "--approval-mode", "yolo"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    proc.stdin.write(PROMPT.encode())
    proc.stdin.close()

    found = False
    deadline = time.time() + TIMEOUT

    while True:
        if time.time() > deadline:
            print("TIMEOUT — killing process")
            proc.kill()
            break
        line = proc.stdout.readline()
        if not line:
            break
        try:
            e = json.loads(line)
            t = e.get("type", "")
            if t == "tool_use":
                params = e.get("parameters", {})
                cmd = params.get("command", "") if isinstance(params, dict) else ""
                tool = e.get("tool_name", "")
                print(f"  tool_use: {tool} | {cmd[:100]}")
                if "get_new_messages" in cmd:
                    found = True
                    print("  ✅ get_new_messages.py called via run_command!")
            elif t == "tool_result" and found:
                r = str(e.get("result", ""))
                print(f"  tool_result: {r[:120]}")
        except Exception:
            pass

    proc.wait()
    print()
    if found:
        print("✅ PASS — agent correctly called get_new_messages.py via run_command")
        sys.exit(0)
    else:
        print("❌ FAIL — agent did not call get_new_messages.py via run_command")
        sys.exit(1)

if __name__ == "__main__":
    main()
