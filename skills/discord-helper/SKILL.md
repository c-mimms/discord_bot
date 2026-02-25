---
name: discord-helper
description: Interact with the user via a Discord bot to send and receive messages. Use when you need to send a notification, ask for confirmation, or check for user input via Discord.
---

# Discord Helper

This skill provides access to the Discord bot helpers to communicate with the user via DM.

## Key Actions

### Send a Message
To send a message to the user, run the following command from the root of the project:

```bash
python3 discord_bot/send_message.py "Your message here"
```

The `DISCORD_BOT_TOKEN` and `DISCORD_USER_ID` environment variables must be set in the `.env` file for this to work.

### Read Messages
To check for incoming messages from the user, read the `discord_bot/messages.json` file. 

#### Get Last Messages
You can use the helper script within this skill to get the last `N` messages:

```bash
node scripts/get_last_messages.cjs [limit]
```

#### Message Format
For the schema of the messages stored in `messages.json`, see [references/message-format.md](references/message-format.md).

### Run the Bot
To start the bot and listen for incoming messages, run:

```bash
python3 discord_bot/bot.py
```

This is a long-running process and should be run in the background if needed.

## Configuration
The bot requires the following variables in a `.env` file at the project root:
- `DISCORD_BOT_TOKEN`: The bot's authentication token.
- `DISCORD_USER_ID`: The Discord ID of the user the bot communicates with.
