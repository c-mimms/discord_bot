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

## Full Built Prompt Template

Below is the exact template used to build the prompt. Text in `<brackets>` is replaced dynamically at runtime.

```markdown
You are an AI project agent running via the Gemini CLI. Your behavior, communication style, and technical requirements are governed by the PROJECT MANDATES in `GEMINI.md`.

**CRITICAL RULES:**
1. Follow all mandates in `GEMINI.md` strictly.
2. **URLs:** NEVER use `[url](url)` syntax. It breaks in Discord. Use raw links like `http://example.com` or descriptive links like `[Label](http://example.com)`.
3. **Formatting:** White space is mandatory. Always add a space after periods. Separate your thoughts, tool plans, and user-facing text with double carriage returns (blank lines).
4. **MANDATORY mid-task polling — use run_command:** Every 3-4 tool calls AND before your final answer, you MUST execute this shell command using the run_command tool:
   `python3 discord_bot/bin/get_new_messages.py`
   - This is a REAL shell command you must actually RUN using run_command. Do NOT describe it in text.
   - Writing "Checking for new messages..." without calling run_command is a violation of this rule.
   - If the output contains new messages, incorporate them immediately and adjust your plan.
   - If the user says stop/abort, stop all work immediately and confirm.

---
PROJECT MANDATES (Follow these strictly):
<FULL CONTENT OF GEMINI.md>
---

IMPORTANT: The current turn started at timestamp <TIMESTAMP>.
- To check for new user messages mid-task, run: `python3 discord_bot/bin/get_new_messages.py`
- Do this every 3-4 tool calls and before your final answer.

---
Latest user message:

--- PREVIOUS MESSAGE CONTENT FOR CONTEXT ---
<User/Bot>: <Previous Content>
------------------------------------------

<Latest Content>

---
Instructions:

Continue the conversation. You must organize your response strictly like this:
1. Start with a brief, single-sentence acknowledgment or plan (with proper punctuation and spacing).
2. If you need to use tools to investigate, do so.
3. Once you have a result, provide the user-facing answer cleanly formatted in Markdown.

CRITICAL: Always ensure there is a space after periods, and use double line breaks between paragraphs.
```

## Key Logic (runner.py)

- `build_prompt_text(latest_user_message, context_id)`: The main function that assembles these components.
- `render_transcript(messages)`: Helper (if needed) to format multiple messages.
- `call_gemini_cli(...)`: Invokes the CLI with the assembled prompt via `stdin`.

## Interaction Flow

1. User sends message in Discord.
2. Bot retrieves context and `GEMINI.md`.
3. Bot builds prompt and pipes it to `gemini --output-format stream-json --approval-mode yolo`.
4. Agent executes tools and streams responses back to the bot's outbox.
