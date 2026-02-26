#!/usr/bin/env python3
"""
Quick diagnostic: run gemini with a tight, explicit prompt that forces it
to call run_command immediately, and dump all stream-json events.
"""
import asyncio, json, os, sys, time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
REPO_ROOT = os.path.dirname(REPO_ROOT)

from src.db.queries import create_context, insert_message, add_message_to_context
from src.app.runner import build_prompt_text

GEMINI_CMD = os.environ.get("GEMINI_CLI_CMD", "gemini")

TIGHT_PROMPT = """\
You are being tested. Your ONLY task is:
1. Run this shell command RIGHT NOW using run_command:
   python3 discord_bot/bin/get_new_messages.py
2. Print the output verbatim.
3. Say "test complete" and stop.

Do not do anything else. Do not browse the web. Just run that one command and stop.
"""

async def main():
    ctx_id = create_context(reply_channel_id=888)
    msg = insert_message("testuser", "run get_new_messages test", "user", channel_id=888)
    add_message_to_context(ctx_id, msg["id"])
    turn_start = float(msg["timestamp"])

    env = os.environ.copy()
    env["DISCORD_CONTEXT_ID"] = ctx_id
    env["DISCORD_TURN_START_TS"] = str(turn_start)
    env["TERM"] = "dumb"
    env["GEMINI_CLI_NON_INTERACTIVE"] = "1"
    env["DISCORD_OUTBOX_ONLY"] = "1"

    print(f"[DIAG] ctx={ctx_id}, turn_start={turn_start}")

    proc = await asyncio.create_subprocess_exec(
        GEMINI_CMD, "--output-format", "stream-json", "--approval-mode", "yolo",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=REPO_ROOT,
        env=env,
    )
    proc.stdin.write(TIGHT_PROMPT.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    found = False
    start = time.time()
    while time.time() - start < 60:
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=2.0)
        except asyncio.TimeoutError:
            if proc.returncode is not None: break
            continue
        if not line: break
        raw = line.decode(errors="replace").strip()
        try:
            e = json.loads(raw)
            t = e.get("type","")
            if t == "tool_use":
                params = e.get("parameters", {})
                print(f"  [tool_use] tool={e.get('tool_name')} cmd={params.get('command','')[:120]}")
                if "get_new_messages" in str(params):
                    found = True
                    print("  ✅ get_new_messages.py called!")
            elif t == "tool_result":
                print(f"  [tool_result] {str(e.get('result',''))[:200]}")
            elif t == "message" and e.get("role") == "assistant":
                txt = (e.get("content") or "")
                if txt.strip():
                    print(f"  [msg] {txt[:150]}")
        except Exception:
            pass

    await proc.wait()
    print(f"\n[DIAG] Exit code: {proc.returncode}")
    print(f"[DIAG] get_new_messages called: {'✅ YES' if found else '❌ NO'}")
    return found

if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
