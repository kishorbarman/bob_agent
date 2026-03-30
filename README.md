# Bob — Personal AI Agent on Telegram

Bob is a personal AI assistant that lives in Telegram. Powered by Gemini, he can answer questions, search the web, check your calendar, read your emails, and more — all from a simple chat interface.

For complete operational instructions, see [`INSTRUCTION_MANUAL.md`](INSTRUCTION_MANUAL.md).

## Capabilities

| Tool | What Bob can do |
|------|----------------|
| 💬 Chat | General Q&A, reasoning, writing — powered by Gemini |
| 🎛 UX style | Clean chat-first UX with `/tools`, `/style`, `/model`, `/prefs` |
| 🧭 Command menu | `/help`, `/tools`, `/prefs` guided flows |
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
| ⏰ Proactive modes | Daily briefs, quiet hours, watchers, proactive nudges/digest |
| 🎤 Voice | Voice note handling with fallback messaging (transcription currently disabled) |
| 🖼 Files & images | Image understanding, PDF/text summarization, file follow-up Q&A |

## Requirements

- Python 3.9+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- A Gemini API key
- A Google Cloud project with Calendar and Gmail APIs enabled (for those features)

## Setup

If you want the full setup + operations guide (including troubleshooting and validation), read [`INSTRUCTION_MANUAL.md`](INSTRUCTION_MANUAL.md).

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
GEMINI_API_KEY=your_gemini_api_key
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
| `/help` | Show capabilities and example prompts |
| `/tools` | Open one-tap tool launcher |
| `/prefs` | Update response style, language, and timezone |
| `/style` | Set response style with readable options |
| `/model` | Choose model: Gemini 3.1 Flash-Lite Preview or Gemini 3.1 Pro Preview |
| `/reset` | Clear conversation history |
| `/brief` | Enable/disable/configure daily brief mode |
| `/quiet` | Set quiet-hours window for proactive notifications |
| `/watchers` | Manage proactive watchers (news/price) |
| `/proactive` | Control proactive system, nudges, and digest mode |

## Project Structure

```
bob_agent/
├── bot.py               # Main bot — tools, handlers, agentic loop
├── google_services.py   # Google Calendar & Gmail integration
├── INSTRUCTION_MANUAL.md # Detailed setup, usage, troubleshooting manual
├── requirements.txt     # Python dependencies
├── .env                 # Your API keys (never commit this)
├── .env.example         # Example env file
├── credentials.json     # Google OAuth credentials (never commit this)
└── token.json           # Google OAuth token (auto-generated)
```

## Codebase Model

### Runtime & Process Model

- `bot.py` is the main entrypoint and runs a long-lived Telegram polling loop (`app.run_polling()`).
- The bot is "always on" by keeping this Python process alive (for example via `tmux`).
- Message handling is asynchronous through `python-telegram-bot` handlers.

### Agentic Loop

- Incoming text messages are handled in `handle_message()`.
- The bot keeps per-user conversation state in memory (`conversations` dict keyed by Telegram user ID).
- Each request sends recent history to Gemini with tool definitions.
- The agent loop executes tool/function calls when requested by the model, appends function responses, and continues until a final text response is produced.

### Tool Architecture

- Tool declarations and dispatch logic live in `bot.py` (`TOOLS` + `run_tool()`).
- Local utility/API tools in `bot.py` include:
  - time (`zoneinfo`)
  - weather (Open-Meteo)
  - web/news search (DuckDuckGo)
  - Wikipedia
  - calculator
  - country info
  - dictionary
- Google/Nest integrations are separated into `google_services.py`:
  - Google Calendar (upcoming/search)
  - Gmail (recent/search)
  - Nest SDM devices, thermostat, cameras

### State, Auth, and External Dependencies

- Bot/API credentials are loaded from environment variables (`TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `NEST_PROJECT_ID`).
- Optional ops alerting uses `ADMIN_CHAT_ID` (Telegram) and/or `ALERT_WEBHOOK_URL` (Slack).
- Google OAuth uses:
  - `credentials.json` (OAuth client credentials)
  - `token.json` (persisted user access/refresh token)
- Conversation history is persisted in SQLite and rehydrated on restart.

### Current Operational Notes

- The bot is currently single-process and polling-based (not webhook-based).
- It now includes reliability and operations hardening:
  - persisted conversation history
  - retry/timeout/circuit behavior for external calls
  - structured ops logs + alerting hooks
  - optional proactive scheduler modes

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
