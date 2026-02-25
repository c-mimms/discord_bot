# Discord Message Format

The `discord_bot/messages.json` file contains a JSON array of message objects.

## Message Object Schema

Each message object has the following fields:

- `author` (string): The Discord username and discriminator of the message author (e.g., `user#1234`).
- `content` (string): The text content of the message.
- `source` (string): Either `"user"` (message from the user to the bot) or `"bot"` (message from the bot to the user).
- `timestamp` (number): A Unix timestamp (seconds since epoch) representing when the message was sent or received.

## Example

```json
[
  {
    "author": "user#1234",
    "content": "Hello bot!",
    "source": "user",
    "timestamp": 1677183591.0
  },
  {
    "author": "BotName#5678",
    "content": "Hello user!",
    "source": "bot",
    "timestamp": 1677183600.0
  }
]
```
