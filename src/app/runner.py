import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, AsyncGenerator
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class GeminiEvent:
    type: str  # "text", "tool_use", "tool_result", "error", "status"
    content: str
    metadata: Optional[Dict[str, Any]] = None

SYSTEM_PROMPT = """
You are an AI project agent running via the Gemini CLI. Your behavior, communication style, and technical requirements are governed by the PROJECT MANDATES in `GEMINI.md`.

**CRITICAL:**
1. Follow all mandates in `GEMINI.md` strictly.
2. Use the **MCP tool menu** for `get_conversation_history()` and `get_new_messages()`. 
3. NEVER try to run `mcp_server.py` or these tools via a shell command.
4. **URLs:** NEVER use `[url](url)` syntax. It breaks in Discord. Use raw links like `http://example.com` or descriptive links like `[Label](http://example.com)`.
"""


def render_transcript(messages: List[Dict[str, Any]]) -> str:
    """
    Render the full conversation as plain text lines like:
      User: ...
      Bot: ...
    """
    sorted_messages = sorted(messages, key=lambda m: m.get("timestamp", 0))
    lines: List[str] = []

    for msg in sorted_messages:
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        role = "User" if msg.get("source") == "user" else "Bot"
        lines.append(f"{role}: {content}")

    return "\n".join(lines)


def build_prompt_text(latest_user_message: Dict[str, Any]) -> str:
    latest_content = (latest_user_message.get("content") or "").strip()
    turn_start_ts = float(latest_user_message.get("timestamp", time.time()))

    # Read project mandates (GEMINI.md) if available
    mandates = ""
    try:
        # GEMINI.md is usually in the project root
        project_root = os.path.dirname(os.path.dirname(__file__))
        mandate_path = os.path.join(project_root, "GEMINI.md")
        if os.path.exists(mandate_path):
            with open(mandate_path, "r") as f:
                mandates = f.read().strip()
    except Exception as e:
        print(f"[{time.ctime()}] WARNING: Could not read GEMINI.md: {e}", flush=True)

    prompt_parts = [
        SYSTEM_PROMPT.strip(),
        "",
        "---",
        "PROJECT MANDATES (Follow these strictly):",
        mandates if mandates else "(No mandates found in GEMINI.md)",
        "---",
        "",
        f"IMPORTANT: The current turn started at timestamp {turn_start_ts}.",
        f"1. If you need context on previous messages, call `get_conversation_history()`.",
        f"2. If you are about to start a long task, periodically check for new messages using `get_new_messages(since_timestamp={turn_start_ts})`.",
        "",
        "---",
        "Latest user message:",
        "",
        latest_content,
        "",
        "---",
        "Instructions:",
        "",
        "Continue the conversation as the Bot. Based on the latest user message (and any history you fetch), decide whether you should:",
        "- propose or refine a plan,",
        "- ask the user focused questions,",
        "- execute tasks and report progress, or",
        "- summarize what you have done so far.",
        "",
        "Respond with what you would send back to the user in Discord.",
    ]

    return "\n".join(prompt_parts)


def select_latest_user_message(messages: List[Dict], after_timestamp: float) -> Optional[Dict]:
    candidates = [
        m
        for m in messages
        if m.get("source") == "user" and float(m.get("timestamp", 0)) > float(after_timestamp)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda m: float(m.get("timestamp", 0)))


async def call_gemini_cli(
    prompt_text: str,
    *,
    gemini_cmd: str = "gemini",
    timeout_s: float = 600,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> AsyncGenerator[GeminiEvent, None]:
    print(f"[{time.ctime()}] Invoking Gemini CLI (Streaming): {gemini_cmd}", flush=True)
    print(f"[{time.ctime()}] Prompt length: {len(prompt_text)} chars", flush=True)
    
    args = [
        gemini_cmd,
        "--output-format", "stream-json",
        "--approval-mode", "yolo",
    ]
    
    if env is None:
        env = os.environ.copy()
    
    # Force non-interactive/dumb terminal behavior
    env["TERM"] = "dumb"
    env["GEMINI_CLI_NON_INTERACTIVE"] = "1"
    env.setdefault("DISCORD_OUTBOX_ONLY", "1")

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        # Yield PID for tracking
        yield GeminiEvent(type="status", content="spawned", metadata={"pid": proc.pid})
    except FileNotFoundError:
        yield GeminiEvent(
            type="error", 
            content=f"I couldn't find the `gemini` CLI at `{gemini_cmd}`. Please ensure it is installed and in your PATH."
        )
        return

    try:
        print(f"[{time.ctime()}] Sending prompt to stdin...", flush=True)
        proc.stdin.write(prompt_text.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()
        
        # Read JSONL from stdout manually to avoid readline() limits
        buffer = bytearray()
        
        def process_line(line: str):
            line = line.strip()
            if not line:
                return None
                
            try:
                event = json.loads(line)
                ev_type = event.get("type")
                
                # Raw response logging for deep debugging
                try:
                    resp_log_path = os.path.join(os.path.dirname(__file__), "gemini_responses.log")
                    with open(resp_log_path, "a") as f:
                        f.write(f"[{time.ctime()}] {line.strip()}\n")
                except Exception:
                    pass

                if ev_type == "message":
                    chunk_text = event.get("content", "")
                    
                    # Filter out prompt echo (CLI echoes the prompt in stream-json mode)
                    if chunk_text.strip() == prompt_text.strip():
                        print(f"[{time.ctime()}] Filtering prompt echo.", flush=True)
                        return None

                    # Check if this is an assistant (model) message
                    role = (event.get("metadata") or {}).get("role")
                    if role == "user":
                        return None
                        
                    if chunk_text:
                        return GeminiEvent(type="text", content=chunk_text)
                elif ev_type == "tool_use":
                    tool_name = event.get("content", "")
                    return GeminiEvent(type="tool_use", content=tool_name, metadata=event.get("metadata"))
                elif ev_type == "tool_result":
                    return GeminiEvent(type="tool_result", content=event.get("content", ""), metadata=event.get("metadata"))
                elif ev_type == "error":
                    return GeminiEvent(type="error", content=event.get("content", ""))
                elif ev_type == "result":
                    # Final result, contains stats etc.
                    pass
            except json.JSONDecodeError:
                # Sometimes there's non-json output mixed in if something goes wrong
                print(f"[{time.ctime()}] WARNING: Non-JSON output from CLI: {line}", flush=True)
            return None

        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                # Process any remaining data in the buffer
                if buffer:
                    line = buffer.decode("utf-8", errors="replace")
                    ev = process_line(line)
                    if ev:
                        yield ev
                break
                
            buffer.extend(chunk)
            while b'\n' in buffer:
                line_b, remaining = buffer.split(b'\n', 1)
                buffer = bytearray(remaining)
                line = line_b.decode("utf-8", errors="replace")
                ev = process_line(line)
                if ev:
                    yield ev

        await proc.wait()
        print(f"[{time.ctime()}] Gemini CLI finished with return code {proc.returncode}", flush=True)
        
    except asyncio.TimeoutError:
        print(f"[{time.ctime()}] ERROR: Gemini CLI timed out", flush=True)
        try:
            proc.kill()
        except Exception:
            pass
        yield GeminiEvent(type="error", content="The `gemini` CLI took too long to respond.")
    except Exception as e:
        print(f"[{time.ctime()}] ERROR in call_gemini_cli: {e}", flush=True)
        yield GeminiEvent(type="error", content=f"An internal error occurred: {e}")

    # Capture any remaining stderr
    stderr_b = await proc.stderr.read()
    if stderr_b:
        stderr = stderr_b.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            print(f"[{time.ctime()}] STDERR from failed CLI: {stderr}", flush=True)
            yield GeminiEvent(type="error", content=f"CLI failed with error: {stderr}")


async def run_next_turn(
    latest_message: Dict[str, Any],
    *,
    gemini_cmd: str = "gemini",
    project_root: Optional[str] = None,
):
    print(f"[{time.ctime()}] Processing latest user message: {latest_message.get('content')[:50]}...", flush=True)
    prompt_text = build_prompt_text(latest_message)

    env = os.environ.copy()
    env.setdefault("DISCORD_OUTBOX_ONLY", "1")

    # Yield the timestamp of the message we are processing so bot.py can track it
    yield GeminiEvent(type="status", content="starting", metadata={"timestamp": float(latest_message.get("timestamp", 0))})

    async for event in call_gemini_cli(prompt_text, gemini_cmd=gemini_cmd, cwd=project_root, env=env):
        yield event
