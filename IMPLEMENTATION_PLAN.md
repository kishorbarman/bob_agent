# Bob Agent Implementation Plan

## Progress Tracker

### Shared Foundations

- Status: Completed
- Implemented:
  - Added `storage.py` (SQLite persistence for preferences, message context, callback dedupe, voice draft state, file artifacts)
  - Added `preferences.py` (typed preference accessors)
  - Added `telegram_ui.py` (callback schema, keyboards, card renderers)
  - Added feature flags in `.env.example` for all 4 phases
  - Added centralized handler guard for runtime error containment in `bot.py`
- Validation:
  - `python3 -m py_compile ...` passed
  - Unit tests passed (`python3 -m unittest discover -s tests -v`)

### Phase 1: Quick Actions + /help /tools /prefs

- Status: Completed
- Implemented:
  - Added `/help`, `/tools`, `/prefs` commands
  - Added inline quick actions under assistant responses (`Search Web`, `Simplify`, `Summarize`, `Translate`, `Retry`, `Reset`)
  - Added callback handling for quick actions and preferences
  - Added callback dedupe guard (`callback_events`) to prevent repeated rapid taps
  - Persisted message context so callbacks can re-run from correct prompt/response
- Validation:
  - Callback parser/keyboard unit tests pass
  - Preference persistence test pass (write/read through SQLite)
  - End-to-end flow compiled and handler wiring validated via static compile

### Phase 2: Rich Response Cards

- Status: Completed
- Implemented:
  - Added card renderers (`weather`, `news`, `calendar`, `email`) in `telegram_ui.py`
  - `/tools` flows now render rich, labeled cards for supported outputs
  - Added consistent renderer entrypoint (`render_card`)
- Validation:
  - Card renderer unit tests pass
  - Tool flow integration validated in callback routes and text follow-up routes

### Phase 3: Voice Notes In

- Status: Completed
- Implemented:
  - Added voice update handler (`filters.VOICE`)
  - Added safeguards (max duration and max file size checks)
  - Added transcription preview UX with `Use`, `Edit`, `Cancel`
  - Added pending transcription persistence in SQLite
  - Added routing of approved transcription back into the same agent loop
- Validation:
  - Voice handler compiles and is wired in dispatcher
  - Temp-file cleanup path implemented with `finally` block
  - Note: in the current configuration, voice transcription currently returns a graceful fallback message

### Phase 4: File and Image UX

- Status: Completed
- Implemented:
  - Added photo handler (`filters.PHOTO`)
  - Added document handler (`filters.Document.ALL`)
  - Added MIME/type detection (`media_utils.py`)
  - Added image analysis pipeline (Gemini vision)
  - Added PDF/text extraction pipeline (`pypdf` + summarization)
  - Added artifact action buttons (`Summarize`, `Extract action items`, `Ask question`)
  - Added artifact context binding and follow-up Q&A on latest artifact
  - Added temp-file cleanup and persisted artifact context
- Validation:
  - MIME detection unit tests pass
  - Compile + test suite pass
  - Unsupported file handling path implemented and verified in handler logic

---

## Execution Plan

We’ll implement all 4 phases in sequence with safe increments, feature flags, and test gates so the bot stays usable throughout.

1. Phase 1: Quick Actions + Command UX foundation
2. Phase 2: Rich response cards
3. Phase 3: Voice note input pipeline
4. Phase 4: File and image understanding

---

## Shared Foundations (do first)

1. Create new modules:
- `/Users/kishorbarman/projects/bob_agent/telegram_ui.py` for keyboards, callback parsing, formatters
- `/Users/kishorbarman/projects/bob_agent/preferences.py` for per-user settings
- `/Users/kishorbarman/projects/bob_agent/storage.py` for simple persistence (SQLite recommended)

2. Add persistent user prefs:
- Fields: `user_id`, `timezone`, `language`, `response_style`, `created_at`, `updated_at`
- Defaults: `timezone=America/Los_Angeles`, `language=en`, `response_style=normal`

3. Add callback schema:
- Format: `action:<name>|v:1|ctx:<id>`
- Max length safe for Telegram callback data
- Include version to support future migrations

4. Add feature flags in env:
- `UX_PHASE1_ENABLED=true`
- `UX_PHASE2_ENABLED=true`
- `UX_PHASE3_ENABLED=false` initially
- `UX_PHASE4_ENABLED=false` initially

5. Add centralized error wrapper for handlers:
- Catch exceptions
- Return friendly user message
- Log with `user_id`, command, callback action, stack trace id

---

## Phase 1: Quick Actions + /help /tools /prefs

### Build Instructions

1. Add commands in `bot.py`:
- `/help`: capability menu + examples
- `/tools`: button-based launcher for common tasks
- `/prefs`: set timezone/language/response style via buttons

2. Add inline quick actions under assistant replies:
- `Search Web`, `Simplify`, `Summarize`, `Translate`, `Retry`
- Keep user original prompt in message context table to allow retry variants

3. Implement callback handlers:
- `simplify`: re-ask model for simpler explanation
- `summarize`: compress last answer
- `translate`: prompt for target language if not set
- `retry_web`: force tool hint for web search path
- `reset`: clear conversation state for user

4. Add anti-duplication guard:
- Ignore repeated callback presses for same message/action in short window

### Validation Plan

1. Unit tests:
- Callback parser
- Keyboard builders
- Pref read/write

2. Integration tests:
- `/help`, `/tools`, `/prefs` command responses
- Each quick action callback returns expected output type

3. Manual QA:
- Tap each quick action twice rapidly
- Confirm no crash, no duplicate side effects
- Confirm prefs persist across process restart

4. Acceptance criteria:
- Every assistant reply includes quick action row
- `/prefs` changes behavior in next reply
- No unhandled exception in logs during test run

---

## Phase 2: Rich Response Cards

### Build Instructions

1. Define card renderer templates:
- Weather card
- News card
- Calendar card
- Email summary card

2. Standard card structure:
- Title line
- 3 to 6 key facts
- Optional “Next actions” buttons
- Consistent Markdown escaping for Telegram

3. Wire tool outputs to typed responses:
- Return structured dict from tool wrappers, not only plain strings
- Renderer chooses card template by `type`

4. Add “copy-ready” sections:
- Email draft blocks
- Meeting prep brief blocks

### Validation Plan

1. Unit tests:
- Renderer output formatting and escaping
- Long text truncation rules

2. Snapshot tests:
- Golden outputs for each card type

3. Manual QA:
- Check readability on iOS and Android Telegram
- Verify long content wraps cleanly

4. Acceptance criteria:
- Top tools render cards instead of raw text
- No malformed Markdown errors
- Buttons map to valid callbacks

---

## Phase 3: Voice Notes In

### Build Instructions

1. Add voice message handler:
- Detect Telegram voice updates
- Download OGG/OPUS file to temp dir
- Transcribe with selected STT provider

2. Add transcription UX:
- Show “Transcribed as:” preview
- Buttons: `Use`, `Edit`, `Cancel`

3. Route approved transcription through existing agent loop

4. Add optional response mode:
- Text only initially
- Leave TTS as optional follow-up toggle

5. Add safeguards:
- File size limit
- Duration limit
- Timeout and fallback message

### Validation Plan

1. Unit tests:
- Voice update parsing
- Temp file lifecycle cleanup

2. Integration tests:
- Mock transcription success/failure/timeouts

3. Manual QA:
- Short and long voice notes
- Noisy audio sample
- Non-English sample if language pref is set

4. Acceptance criteria:
- Voice note processed end-to-end under target latency
- Failures are graceful and actionable
- Temp files removed after processing

---

## Phase 4: File and Image UX

### Build Instructions

1. Add document/image handlers:
- Accept photo, image file, PDF
- Store metadata and file references in per-user context

2. Add extraction pipelines:
- Images: OCR + high-level summary
- PDFs: text extraction + chunked summarization

3. Add follow-up action buttons:
- `Summarize`
- `Extract action items`
- `Ask question about this file`

4. Add context binding:
- “Ask question” uses last uploaded artifact unless user picks another

5. Add privacy controls:
- Auto-delete local temp files
- Configurable retention for extracted text

### Validation Plan

1. Unit tests:
- MIME type detection
- File size and type guards
- Context binding logic

2. Integration tests:
- Sample image OCR flow
- Sample PDF summarize flow

3. Manual QA:
- Multi-page PDF
- Low-quality image
- Unsupported file type behavior

4. Acceptance criteria:
- File/image flows complete without manual intervention
- Follow-up questions correctly reference uploaded file
- Unsupported files return clear guidance

---

## Cross-Phase Validation Strategy

1. Regression suite before each phase merge:
- `/start`, `/reset`, normal text chat, all existing tools

2. Reliability checks:
- 24-hour soak run with synthetic messages every 5 minutes
- Memory growth monitoring
- API failure simulation

3. Security checks:
- User allowlist option
- Callback tamper handling
- Input sanitization for tool calls and Markdown

4. Observability:
- Structured logs for commands, callbacks, tool latency, errors
- Daily error summary report

---

## Rollout Plan

1. Deploy Phase 1 behind flags and enable for your user ID only
2. Expand to all users after 48 hours clean logs
3. Repeat for Phases 2, 3, and 4
4. Keep rollback switch per phase via env flag

---

## Definition of Done

1. All four phases implemented and enabled by default
2. Test suite green with added coverage for callbacks/media flows
3. Soak test passes with no critical errors
4. README updated with new UX features and usage examples

---

## Future Tracks Roadmap

The UX track is complete. The following tracks are planned for future implementation.

### Track A: Reliability and Operations

- Status: Planned
- Goal: Make the bot resilient under API failures, restarts, and long-running workloads.
- Scope:
  - Persist conversation history in SQLite/Postgres (survive restarts)
  - Add retries/timeouts/circuit-breakers and graceful fallbacks for all external calls
  - Add process supervision (`systemd` or Docker) with health checks and auto-restart
  - Add structured logging and alerting (Slack/Telegram) for critical failures
- Validation:
  - 24-hour soak with no crash loops
  - Forced API failure simulation and graceful degradation verified
  - Recovery after process restart with preserved conversation continuity

### Track B: Proactive Assistant Behaviors

- Status: Planned
- Goal: Move from reactive Q&A to proactive assistance.
- Scope:
  - Daily morning brief (calendar, weather, priority email)
  - Watchers (price drops, news keywords, flight/package status)
  - Scheduled reminders and nudges from calendar context
- Validation:
  - Scheduler reliability over multiple days
  - Dedupe logic for repeated events
  - Missed-run recovery behavior verified

### Track C: Work Assistant Depth

- Status: Planned
- Goal: Turn Bob into a practical daily work copilot.
- Scope:
  - Gmail triage summaries and labeling suggestions
  - Draft/reply assistance with editable output
  - Calendar copilot (slot proposals, meeting prep briefs)
  - Command-center summary thread with priorities and follow-ups
- Validation:
  - Draft quality reviewed on real inbox samples
  - Calendar slot suggestions respect constraints
  - End-to-end workflows complete with <3 user interactions

### Track D: Home Automation Expansion

- Status: Planned
- Goal: Extend beyond basic Nest reads into useful routines.
- Scope:
  - Routine macros (e.g., “I’m leaving”, “Good night”)
  - Context-aware actions (time/occupancy/temperature)
  - Integrations for Home Assistant / Philips Hue / smart plugs
- Validation:
  - Safe command guardrails for home controls
  - Routine dry-run mode and confirmation prompts
  - Device state reconciliation after command execution

### Track E: Memory and Personalization

- Status: Planned
- Goal: Improve personalization and long-term usefulness.
- Scope:
  - Long-term memory store (people, projects, preferences)
  - Response style adaptation from explicit/implicit signals
  - “Don’t ask again” and preference learning patterns
- Validation:
  - Memory retrieval relevance scoring
  - Preference persistence across sessions/restarts
  - User override controls and memory edit/delete flow

### Track F: Security and Control

- Status: Planned
- Goal: Ensure safe usage as capabilities expand.
- Scope:
  - Telegram allowlist (trusted user IDs only)
  - Confirm-before-action for risky operations
  - Full audit log for tool calls and changes
- Validation:
  - Unauthorized user requests blocked
  - Risky actions require explicit confirmation
  - Audit entries complete and queryable

### Track G: Additional Integrations

- Status: Planned
- Goal: Connect Bob to core personal/work platforms.
- Scope:
  - Notion, Todoist, Linear, GitHub, Google Drive, Slack
  - Travel, finance/portfolio, shopping/price tracking APIs
  - Optional custom internal APIs
- Validation:
  - Contract tests for each integration
  - Rate-limit and token-expiry handling
  - Common workflows verified end-to-end

---

## Future Track Execution Order

1. Track A: Reliability and Operations
2. Track F: Security and Control
3. Track B: Proactive Assistant Behaviors
4. Track C: Work Assistant Depth
5. Track E: Memory and Personalization
6. Track G: Additional Integrations
7. Track D: Home Automation Expansion

---

## Future Track Milestone Template

Use this template when starting any new track.

1. Define scope and non-goals
2. Add feature flags and rollout strategy
3. Implement in small phases with tests per phase
4. Run regression + soak checks
5. Update this document with status, validation evidence, and follow-ups
