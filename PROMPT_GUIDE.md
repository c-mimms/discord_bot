# Discord Bot Prompt Guide

This document describes how the Discord bot constructs the prompt sent to the Gemini CLI. The logic is primarily located in `discord_bot/src/app/runner.py`.

## Prompt Structure

The prompt is a multi-part text block constructed in the following order:

### 1. System Prompt
Defines the AI's identity and critical operational rules.
- **Identity:** AI project agent running via Gemini CLI.
- **Rules:** 
  - Strict adherence to `GEMINI.md`.
  - URL formatting (no `[url](url)`).
  - Mandatory polling for new messages via `python3 discord_bot/bin/get_new_messages.py` using the `run_command` tool.

### 2. Project Mandates (`GEMINI.md`)
The full content of the root `GEMINI.md` is injected here. This ensures the agent always has the latest project rules and workflows in its context.

### 3. Turn Metadata
Includes the current timestamp and a recurring injection of the mandatory polling command to ensure it remains top-of-mind.

### 4. Message Content
The bot identifies the latest user message and, if applicable, prepends the content of the immediately preceding message (User or Bot) for short-term context.

### 5. Final Instructions
Enforces strict output formatting:
- Brief acknowledgment or plan.
- Tool usage for investigation.
- Cleanly formatted Markdown for the final answer.
- Mandatory whitespace and double line breaks.

## Key Logic (runner.py)

- `build_prompt_text(latest_user_message, context_id)`: The main function that assembles these components.
- `render_transcript(messages)`: Helper (if needed) to format multiple messages.
- `call_gemini_cli(...)`: Invokes the CLI with the assembled prompt via `stdin`.

## Interaction Flow

1. User sends message in Discord.
2. Bot retrieves context and `GEMINI.md`.
3. Bot builds prompt and pipes it to `gemini --output-format stream-json --approval-mode yolo`.
4. Agent executes tools and streams responses back to the bot's outbox.
