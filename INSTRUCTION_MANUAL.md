# Bob Agent Instruction Manual

## 1) Overview

Bob is an always-on Telegram assistant powered by Gemini, with optional Google integrations (Calendar, Gmail, Nest), plus Telegram UX upgrades (guided menus, voice notes, and file/image understanding).

This manual explains:
- How to install and run Bob
- How to configure integrations and feature flags
- How each Telegram UX feature works
- How to validate and troubleshoot the system
- How to operate Bob safely in long-running mode

## 2) System Requirements

- Python 3.9+
- Telegram bot token (`TELEGRAM_BOT_TOKEN`)
- Gemini API key (`GEMINI_API_KEY`)
- Optional: Google OAuth credentials for Calendar/Gmail/Nest

## 3) Project Files

Core files:
- `bot.py`: Main runtime, handlers, UX flows, and model/tool orchestration
- `google_services.py`: Google Calendar/Gmail/Nest API integration
- `storage.py`: SQLite persistence (preferences, callback dedupe, file context, voice draft)
- `preferences.py`: User preference read/write helper
- `telegram_ui.py`: Keyboards, callback schema, and response card rendering
- `media_utils.py`: File/document type detection helpers

Planning and docs:
- `IMPLEMENTATION_PLAN.md`: Implementation plans and progress tracking
- `README.md`: Quickstart and high-level architecture
- `INSTRUCTION_MANUAL.md`: This detailed manual

## 4) Installation

1. Install dependencies:

```bash
pip3 install -r requirements.txt
```

2. Copy env template:

```bash
cp .env.example .env
```

3. Fill required variables in `.env`:

```env
TELEGRAM_BOT_TOKEN=...
GEMINI_API_KEY=...
```

4. Optional variables:

```env
NEST_PROJECT_ID=...
UX_PHASE2_ENABLED=true
UX_PHASE3_ENABLED=true
UX_PHASE4_ENABLED=true
```

## 5) Google Integrations Setup (Optional)

1. In Google Cloud Console, create/select a project.
2. Enable APIs:
- Google Calendar API
- Gmail API
- Smart Device Management API (if using Nest)
3. Create OAuth client credentials (Desktop app).
4. Save the downloaded file as `credentials.json` in project root.
5. Add your Google account under OAuth consent test users.
6. On first run, Bob opens browser OAuth consent and writes `token.json`.

## 6) Running Bob

### Foreground run

```bash
set -a && source .env && set +a
python3 bot.py
```

### Keep-alive run with tmux

```bash
tmux new -s bob
set -a && source .env && set +a
python3 bot.py
# detach: Ctrl+B then D
# reattach: tmux attach -t bob
```

## 7) Telegram Commands and UX

### Commands

- `/start`: Initializes user session and greeting
- `/help`: Shows capability guide and example prompts
- `/tools`: Opens one-tap tool launcher
- `/prefs`: Opens style/language/timezone preferences menu
- `/style`: Opens readable style-only selector (`short`, `normal`, `detailed`)
- `/model`: Select model (`Gemini 3.1 Flash-Lite Preview` or `Gemini 3.1 Pro Preview`)
- `/reset`: Clears in-memory conversation for current user

### Chat-first interaction style

Bob now replies in plain chat without inline per-message action buttons.
For follow-up operations, ask directly in natural language (for example: "summarize that", "translate to Spanish", or "search the web for the latest").

### Preferences

Preference menu updates and persists:
- Response style (`short`, `normal`, `detailed`)
- Language (`en`, `es`, `fr`)
- Timezone (`America/Los_Angeles`, `America/New_York`, `UTC`)

Preferences are saved in SQLite and survive bot restarts.

## 8) Voice Notes Flow (Phase 3)

### How it works

1. User sends a Telegram voice note.
2. Bob validates limits:
- Max duration: 3 minutes
- Max size: 5 MB
3. Bob currently validates the voice note, then returns a clear fallback message in this configuration.
4. Text/image/PDF flows remain fully supported.

## 9) File and Image Flow (Phase 4)

### Supported inputs

- Telegram photo
- Image document (png/jpg/jpeg/webp)
- PDF document
- Plain text documents

### Processing behavior

- Images:
  - Sent to Gemini vision for text extraction + summary
- PDFs:
  - Text extracted with `pypdf`
  - Summarized into key points/action items
- Text files:
  - Read and summarized

### Post-processing actions

After ingest, Bob offers:
- `Summarize`
- `Extract action items`
- `Ask question`

`Ask question` uses latest uploaded artifact context for Q&A.

## 10) Persistence Model

SQLite database file: `bob.db`

Tables:
- `user_preferences`: per-user timezone/language/style
- `callback_events`: duplicate callback suppression
- `pending_transcriptions`: voice draft state
- `artifacts`: latest file/image context for follow-up Q&A

## 11) Feature Flags

Flags read from env:
- `UX_PHASE2_ENABLED`
- `UX_PHASE3_ENABLED`
- `UX_PHASE4_ENABLED`

Turn a feature off by setting its value to `false`.

## 12) Validation and Testing

### Static/compile checks

```bash
python3 -m py_compile bot.py storage.py preferences.py telegram_ui.py media_utils.py
```

### Unit tests

```bash
python3 -m unittest discover -s tests -v
```

Current test coverage includes:
- Callback schema parsing and keyboard structure
- Preference persistence through SQLite
- Document type detection

## 13) Troubleshooting Guide

### Bot does not start

- Confirm `TELEGRAM_BOT_TOKEN` exists in environment
- Confirm dependencies installed from `requirements.txt`
- Run compile command to detect syntax/import issues

### Gemini errors

- Confirm `GEMINI_API_KEY`
- Check network connectivity
- Check model name availability/permissions

### Google APIs fail

- Confirm `credentials.json` and `token.json` are present
- Re-run OAuth if token expired/revoked
- Confirm required Google APIs are enabled

### Voice does not transcribe

- In the current configuration, voice transcription is intentionally disabled.
- Confirm voice note is under size/duration limits to avoid validation errors.

### File upload unsupported

- Ensure mime type is image/pdf/text
- For scanned image-only PDFs, text extraction may be limited

### A follow-up request did not use prior context

- Ask directly with explicit reference (for example: "summarize your previous answer")
- If needed, resend the original prompt to rebuild context

## 14) Operations Checklist (Always-On)

Daily:
- Confirm process is running (`tmux attach -t bob`)
- Check logs for repeated handler exceptions
- Run quick smoke tests (`/help`, `/tools`, and one natural-language follow-up)

Weekly:
- Test Google tool paths (calendar + email)
- Validate voice and file flow still functioning
- Rotate/revalidate API credentials if needed

## 15) Security and Safety Recommendations

- Keep `.env`, `credentials.json`, `token.json` out of git
- Restrict who can access the bot token
- Add Telegram user allowlist if multiple people can message the bot
- Add explicit confirmation for destructive actions (future write-capable tools)

## 16) Extending Bob

To add a new tool:
1. Implement the function in `bot.py` (or a dedicated module)
2. Add the tool schema to `TOOLS`
3. Add routing in `run_tool()`
4. Add optional `/tools` shortcut and card renderer entry
5. Add unit tests for parser/logic/output formatter

## 17) Known Limitations

- Conversation history is still in-memory and not persisted in DB
- Polling mode is used instead of webhooks
- Some advanced media features rely on external model APIs
- Voice transcription is currently disabled in the current configuration
- PDF extraction quality depends on embedded text quality

## 18) Recommended Next Hardening Steps

1. Persist conversation history in SQLite/Postgres
2. Add process supervisor (`systemd` or Docker healthcheck)
3. Add structured JSON logging + error alerting
4. Add user allowlist and per-action permissions
5. Add retry/backoff wrappers for all network calls
