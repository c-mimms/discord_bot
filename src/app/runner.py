import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, AsyncGenerator
from dotenv import load_dotenv

from src.db.queries import get_messages_for_context, get_context, update_context_session_id

load_dotenv()

# All runtime logs live in discord_bot/ (3 levels up from src/app/runner.py)
_DISCORD_BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GEMINI_RESPONSES_LOG = os.path.join(_DISCORD_BOT_DIR, "gemini_responses.log")
GEMINI_TRACES_DIR = os.path.join(_DISCORD_BOT_DIR, "logs", "gemini_traces")
GEMINI_RESPONSES_LOG = os.path.join(_DISCORD_BOT_DIR, "gemini_responses.log")

@dataclass(frozen=True)
class GeminiEvent:
    type: str  # "text", "tool_use", "tool_result", "error", "status"
    content: str
    metadata: Optional[Dict[str, Any]] = None

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


def build_prompt_text(latest_user_message: Dict[str, Any], context_id: str, ignore_history: bool = False) -> str:
    latest_content = (latest_user_message.get("content") or "").strip()
    turn_start_ts = float(latest_user_message.get("timestamp", time.time()))

    # Fetch previous message for context if in a thread or channel
    context_prefix = ""
    if not ignore_history:
        try:
            relevant_messages = get_messages_for_context(context_id)
        
            # Find the message right before the current one
            prev_msg = None
            current_id = latest_user_message.get("id")
            
            idx = -1
            for i, m in enumerate(relevant_messages):
                if current_id and m.get("id") == current_id:
                    idx = i
                    break
                elif float(m.get("timestamp", 0)) == turn_start_ts:
                    idx = i
                    break

            if idx > 0:
                prev_msg = relevant_messages[idx - 1]
            elif idx == -1 and relevant_messages:
                if float(relevant_messages[-1].get("timestamp", 0)) < turn_start_ts:
                    prev_msg = relevant_messages[-1]

            if prev_msg:
                prev_role = "User" if prev_msg.get("source") == "user" else "Bot"
                prev_text = (prev_msg.get("content") or "").strip()
                if prev_text:
                    context_prefix = f"--- PREVIOUS MESSAGE CONTENT FOR CONTEXT ---\n{prev_role}: {prev_text}\n------------------------------------------\n\n"
        except Exception as e:
            print(f"[{time.ctime()}] [Ctx: {context_id}] WARNING: Could not load previous message context: {e}", flush=True)

    # Read modular prompt components
    system_rules = []
    components_dir = os.path.join(_DISCORD_BOT_DIR, "prompts", "components")
    if os.path.exists(components_dir):
        for filename in sorted(os.listdir(components_dir)):
            if filename.endswith(".md"):
                file_path = os.path.join(components_dir, filename)
                try:
                    with open(file_path, "r") as f:
                        system_rules.append(f.read().strip())
                except Exception as e:
                    print(f"[{time.ctime()}] [Ctx: {context_id}] WARNING: Could not read {filename}: {e}", flush=True)

    prompt_parts = []
    if system_rules:
        prompt_parts.extend(system_rules)

    prompt_parts.extend([
        "---",
        f"IMPORTANT: The current turn started at timestamp {turn_start_ts}.",
        "Latest user message:",
        context_prefix + latest_content
    ])

    prompt_text = "\n".join(prompt_parts)

    dump_dir = os.environ.get("DEBUG_PROMPT_DUMP_DIR")
    if dump_dir and os.path.isdir(dump_dir):
        dump_path = os.path.join(dump_dir, "prompt_dump.txt")
        try:
            with open(dump_path, "w") as f:
                f.write(prompt_text)
        except Exception as e:
            print(f"[{time.ctime()}] [Ctx: {context_id}] WARNING: Could not dump prompt to {dump_path}: {e}", flush=True)

    return prompt_text


async def call_gemini_cli(
    prompt_text: str,
    context_id: str,
    *,
    gemini_cmd: str = "gemini",
    timeout_s: float = 600,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    session_id: Optional[str] = None,
) -> AsyncGenerator[GeminiEvent, None]:
    print(f"[{time.ctime()}] [Ctx: {context_id}] Invoking Gemini CLI (Streaming): {gemini_cmd}", flush=True)
    print(f"[{time.ctime()}] [Ctx: {context_id}] Prompt length: {len(prompt_text)} chars", flush=True)
    
    args = [
        gemini_cmd,
    ]
    if session_id:
        args.extend(["-r", session_id])
        
    args.extend([
        "--output-format", "stream-json",
        "--approval-mode", "yolo",
    ])
    
    # Always record responses to the trace directory (one file per turn)
    os.makedirs(GEMINI_TRACES_DIR, exist_ok=True)
    turn_ts_int = int(time.time() * 1000)
    trace_filename = f"{context_id}_{turn_ts_int}.json"
    responses_path = os.path.join(GEMINI_TRACES_DIR, trace_filename)
    
    dump_dir = os.environ.get("DEBUG_PROMPT_DUMP_DIR")
    if dump_dir and os.path.isdir(dump_dir):
        # Override to dump dir if in testing mode
        responses_path = os.path.join(dump_dir, "recorded_responses.json")
        
    args.extend(["--record-responses", responses_path])

    if os.environ.get("GEMINI_RUNNER_DEBUG") == "1":
        args.append("--debug")
    
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

    stderr_parts: List[str] = []

    async def _drain_stderr():
        while True:
            chunk = await proc.stderr.read(65536)
            if not chunk:
                break
            stderr_parts.append(chunk.decode("utf-8", errors="replace"))

    stderr_task = asyncio.create_task(_drain_stderr())

    try:
        print(f"[{time.ctime()}] [Ctx: {context_id}] Sending prompt to stdin...", flush=True)
        proc.stdin.write(prompt_text.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        deadline = time.monotonic() + timeout_s if timeout_s else None
        
        # Read JSONL from stdout manually to avoid readline() limits
        buffer = bytearray()
        
        def process_line(line: str):
            line = line.strip()
            if not line:
                return None
                
            try:
                event = json.loads(line)
                ev_type = event.get("type")
                
                # Raw response logging — single file at discord_bot/gemini_responses.log
                try:
                    with open(GEMINI_RESPONSES_LOG, "a") as f:
                        f.write(f"[{time.ctime()}] [Ctx: {context_id}] {line.strip()}\n")
                except Exception:
                    pass

                if ev_type == "message":
                    chunk_text = event.get("content", "")
                    
                    # Filter out prompt echo (CLI echoes the prompt in stream-json mode)
                    if chunk_text.strip() == prompt_text.strip():
                        print(f"[{time.ctime()}] [Ctx: {context_id}] Filtering prompt echo.", flush=True)
                        return None

                    # Check if this is an assistant (model) message
                    role = (event.get("metadata") or {}).get("role")
                    if role == "user":
                        return None
                        
                    if chunk_text:
                        return GeminiEvent(type="text", content=chunk_text)
                elif ev_type == "init":
                    return GeminiEvent(type="init", content=event.get("session_id", ""))
                elif ev_type == "tool_use":
                    tool_name = event.get("content", "")
                    return GeminiEvent(type="tool_use", content=tool_name, metadata=event.get("metadata"))
                elif ev_type == "tool_result":
                    return GeminiEvent(type="tool_result", content=event.get("content", ""), metadata=event.get("metadata"))
                elif ev_type == "error":
                    return GeminiEvent(type="error", content=event.get("content", ""))
                elif ev_type == "result":
                    pass
            except json.JSONDecodeError:
                print(f"[{time.ctime()}] [Ctx: {context_id}] WARNING: Non-JSON output from CLI: {line}", flush=True)
            return None

        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                chunk = await asyncio.wait_for(proc.stdout.read(65536), timeout=remaining)
            else:
                chunk = await proc.stdout.read(65536)
            if not chunk:
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

        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            await asyncio.wait_for(proc.wait(), timeout=remaining)
        else:
            await proc.wait()
        print(f"[{time.ctime()}] [Ctx: {context_id}] Gemini CLI finished with return code {proc.returncode}", flush=True)
        
    except asyncio.TimeoutError:
        print(f"[{time.ctime()}] [Ctx: {context_id}] ERROR: Gemini CLI timed out", flush=True)
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        yield GeminiEvent(type="error", content="The `gemini` CLI took too long to respond.")
    except Exception as e:
        print(f"[{time.ctime()}] [Ctx: {context_id}] ERROR in call_gemini_cli: {e}", flush=True)
        yield GeminiEvent(type="error", content=f"An internal error occurred: {e}")
    finally:
        try:
            await stderr_task
        except Exception:
            pass

    stderr = "".join(stderr_parts).strip()
    if stderr:
        if proc.returncode != 0:
            print(f"[{time.ctime()}] [Ctx: {context_id}] STDERR from failed CLI: {stderr}", flush=True)
            yield GeminiEvent(type="error", content=f"CLI failed with error: {stderr}")
        elif os.environ.get("GEMINI_RUNNER_DEBUG") == "1":
            print(f"[{time.ctime()}] [Ctx: {context_id}] DEBUG STDERR: {stderr}", flush=True)


async def run_next_turn(
    latest_message: Dict[str, Any],
    context_id: str,
    *,
    gemini_cmd: str = "gemini",
    project_root: Optional[str] = None,
):
    ctx = get_context(context_id)
    session_id = ctx.get("gemini_session_id") if ctx else None

    print(f"[{time.ctime()}] [Ctx: {context_id}] Processing user message... (Session: {session_id or 'None'})", flush=True)
    prompt_text = build_prompt_text(latest_message, context_id, ignore_history=bool(session_id))

    env = os.environ.copy()
    env.setdefault("DISCORD_OUTBOX_ONLY", "1")
    env["DISCORD_CONTEXT_ID"] = context_id
    env["DISCORD_TURN_START_TS"] = str(latest_message.get("timestamp", 0))

    # Yield the timestamp of the message we are processing so bot.py can track it
    yield GeminiEvent(type="status", content="starting", metadata={"timestamp": float(latest_message.get("timestamp", 0))})

    buffered_events = []
    session_invalid = False

    async for event in call_gemini_cli(prompt_text, context_id=context_id, gemini_cmd=gemini_cmd, cwd=project_root, env=env, session_id=session_id):
        if event.type == "init":
            update_context_session_id(context_id, event.content)
            buffered_events.append(event)
        elif event.type == "error" and session_id and "Invalid session identifier" in event.content:
            session_invalid = True
            break
        elif event.type == "status" and event.content == "spawned":
            buffered_events.append(event)
        else:
            if buffered_events:
                for e in buffered_events: yield e
                buffered_events = []
            yield event

    if session_invalid:
        print(f"[{time.ctime()}] [Ctx: {context_id}] Session {session_id} invalid. Clearing and falling back to cold start.", flush=True)
        update_context_session_id(context_id, None)
        prompt_text = build_prompt_text(latest_message, context_id, ignore_history=False)
        
        async for event in call_gemini_cli(prompt_text, context_id=context_id, gemini_cmd=gemini_cmd, cwd=project_root, env=env, session_id=None):
            if event.type == "init":
                update_context_session_id(context_id, event.content)
            yield event
    else:
        for e in buffered_events:
            yield e
