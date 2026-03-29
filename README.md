# Bob — Personal AI Agent on Telegram

Bob is a personal AI assistant that lives in Telegram. Powered by Claude, he can answer questions, search the web, check your calendar, read your emails, and more — all from a simple chat interface.

## Capabilities

| Tool | What Bob can do |
|------|----------------|
| 💬 Chat | General Q&A, reasoning, writing — powered by Claude |
| 🕐 Time | Current date and time in any timezone |
| 🌤 Weather | Current conditions + 3-day forecast for any city |
| 🔍 Web search | Search the web via DuckDuckGo |
| 📰 News | Latest news on any topic |
| 📖 Wikipedia | Summaries and articles |
| 🧮 Calculator | Math expressions, including trig, log, sqrt |
| 🌍 Country info | Capital, population, languages, currency |
| 📚 Dictionary | Definitions, phonetics, examples |
| 📅 Google Calendar | Upcoming events, search by keyword |
| 📧 Gmail | Recent inbox emails, search by query |

## Requirements

- Python 3.9+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An Anthropic API key
- A Google Cloud project with Calendar and Gmail APIs enabled (for those features)

## Setup

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

### 2. Configure environment variables

Copy the example file and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
ANTHROPIC_API_KEY=your_anthropic_api_key
```

### 3. Google Calendar & Gmail (optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project and enable the **Google Calendar API** and **Gmail API**
3. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
4. Choose **Desktop app**, download the file, and save it as `credentials.json` in this folder
5. Add your Google account as a test user under **OAuth consent screen → Test users**

On first run a browser window will open asking you to approve access. After that, a `token.json` is saved and you won't be prompted again.

### 4. Run

```bash
set -a && source .env && set +a
python3 bot.py
```

### Keep it running with tmux

```bash
brew install tmux            # one-time install
tmux new -s bob              # create session
python3 bot.py               # start bot inside session
# Press Ctrl+B then D to detach — bot keeps running
tmux attach -t bob           # reattach later
```

## Telegram Commands

| Command | Action |
|---------|--------|
| `/start` | Greet Bob and reset conversation |
| `/reset` | Clear conversation history |

## Project Structure

```
bob_agent/
├── bot.py               # Main bot — tools, handlers, agentic loop
├── google_services.py   # Google Calendar & Gmail integration
├── requirements.txt     # Python dependencies
├── .env                 # Your API keys (never commit this)
├── .env.example         # Example env file
├── credentials.json     # Google OAuth credentials (never commit this)
└── token.json           # Google OAuth token (auto-generated)
```

## Adding New Tools

1. Add a function in `bot.py` (or a new file for larger integrations)
2. Add a tool definition to the `TOOLS` list
3. Add a dispatch case in `run_tool()`

## Coming Soon

- Google Calendar event creation
- Gmail send/reply
- Reminders & timers
- Stock & crypto prices
- Spotify integration
