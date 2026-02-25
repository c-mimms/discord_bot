const fs = require('fs');
const path = require('path');

const MESSAGES_FILE = path.join(process.cwd(), 'discord_bot', 'messages.json');

function main() {
  const limit = parseInt(process.argv[2], 10) || 5;

  if (!fs.existsSync(MESSAGES_FILE)) {
    console.log('No messages file found.');
    return;
  }

  try {
    const data = fs.readFileSync(MESSAGES_FILE, 'utf8');
    const messages = JSON.parse(data);
    const lastMessages = messages.slice(-limit);

    console.log(JSON.stringify(lastMessages, null, 2));
  } catch (err) {
    console.error(`Error reading messages file: ${err.message}`);
  }
}

main();
