#!/usr/bin/env python3
"""
Integration test: verify the Gemini agent calls get_new_messages.py mid-task.

Flow:
1. Create a context + initial user message in the DB
2. Start Gemini CLI with the real system prompt, injecting DISCORD_CONTEXT_ID env
3. 5 seconds in, insert a new "interrupt" user message into the DB  
4. Wait for CLI to finish, then scan stream-json output for:
   a) a run_command call containing "get_new_messages"
   b) evidence the agent read the injected message content
"""
import asyncio
import json
import os
import sys
import time

# ── path setup ──────────────────────────────────────────────────────────
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # discord_bot/
sys.path.insert(0, REPO_ROOT)
REPO_ROOT = os.path.dirname(REPO_ROOT)  # repo root (gemini/)

from src.db.database import init_db
from src.db.queries import create_context, insert_message, add_message_to_context
from src.app.runner import build_prompt_text, SYSTEM_PROMPT

GEMINI_CMD = os.environ.get("GEMINI_CLI_CMD", "gemini")
TIMEOUT = 120  # seconds


async def run_test():
    # 1. Set up DB
    ctx_id = create_context(reply_channel_id=999)
    initial_msg = insert_message(
        "testuser",
        "Count slowly from 1 to 5, pausing to check for new messages after each number. "
        "Use run_command to call `python3 discord_bot/bin/get_new_messages.py` between each number. "
        "Report any new messages you find.",
        "user",
        channel_id=999,
    )
    add_message_to_context(ctx_id, initial_msg["id"])

    turn_start = float(initial_msg["timestamp"])
    prompt = build_prompt_text(initial_msg, ctx_id)

    env = os.environ.copy()
    env["DISCORD_CONTEXT_ID"] = ctx_id
    env["DISCORD_TURN_START_TS"] = str(turn_start)
    env["TERM"] = "dumb"
    env["GEMINI_CLI_NON_INTERACTIVE"] = "1"
    env["DISCORD_OUTBOX_ONLY"] = "1"

    print(f"[TEST] ctx_id = {ctx_id}")
    print(f"[TEST] Starting Gemini CLI...")

    proc = await asyncio.create_subprocess_exec(
        GEMINI_CMD, "--output-format", "stream-json", "--approval-mode", "yolo",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=REPO_ROOT,
        env=env,
    )

    # Send the prompt then close stdin
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    found_get_new_messages_call = False
    found_injected_message = False
    all_output = []

    # 2. Inject a new message after 5 seconds into the run
    inject_task_done = False

    async def inject_message_after_delay():
        nonlocal inject_task_done
        await asyncio.sleep(5)
        msg = insert_message(
            "testuser",
            "INTERRUPT: please note I said hello from the middle of the task!",
            "user",
            channel_id=999,
        )
        add_message_to_context(ctx_id, msg["id"])
        print(f"\n[TEST] >>> Injected mid-task message at t+5s (id={msg['id']}) <<<\n")
        inject_task_done = True

    inject_task = asyncio.create_task(inject_message_after_delay())

    # 3. Stream and scan output
    start = time.time()
    while True:
        if time.time() - start > TIMEOUT:
            print("[TEST] TIMEOUT")
            proc.kill()
            break
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
        except asyncio.TimeoutError:
            if proc.returncode is not None:
                break
            continue
        if not line:
            break

        raw = line.decode(errors="replace").strip()
        all_output.append(raw)

        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue

        etype = event.get("type", "")

        if etype == "tool_use":
            params = event.get("parameters", {})
            tool = event.get("tool_name", "")
            cmd = params.get("command", "") if isinstance(params, dict) else ""
            if "get_new_messages" in cmd or "get_new_messages" in str(params):
                found_get_new_messages_call = True
                print(f"[TEST] ✅ Agent called get_new_messages: {cmd}")

        if etype in ("message", "tool_result"):
            content = event.get("content", "") or str(event.get("result", ""))
            if "INTERRUPT" in content or "hello from the middle" in content:
                found_injected_message = True
                print(f"[TEST] ✅ Agent acknowledged injected message!")

    inject_task.cancel()
    await proc.wait()

    # 4. Report
    print("\n" + "="*60)
    print("RESULTS:")
    print(f"  get_new_messages called:    {'✅ YES' if found_get_new_messages_call else '❌ NO'}")
    print(f"  Injected message detected:  {'✅ YES' if found_injected_message else '❌ NO (may need longer task)'}")
    print("="*60)

    if not found_get_new_messages_call:
        print("\nAgent did not call get_new_messages.py.")
        print("Check the stream output below for clues:")
        for line in all_output[-30:]:
            try:
                e = json.loads(line)
                if e.get("type") in ("message", "tool_use"):
                    print(" ", json.dumps(e)[:200])
            except Exception:
                pass

    return found_get_new_messages_call


if __name__ == "__main__":
    result = asyncio.run(run_test())
    sys.exit(0 if result else 1)
