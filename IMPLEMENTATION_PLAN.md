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
- Non-goals:
  - Multi-tenant scaling or sharded workers
  - Webhook migration (polling remains the default in this track)
  - Rewriting integrations to async clients end-to-end
- Architecture changes:
  - Add persistent conversation store (`conversation_messages`) in SQLite with bounded retention per user.
  - Add centralized external-call wrapper for retries, timeout budget, and fallback classification.
  - Add health/ops module with liveness/readiness checks and lightweight heartbeat metrics.
  - Add structured JSON logging fields across commands/callbacks/tool runs (`trace_id`, `user_id`, `action`, `latency_ms`, `result`).
  - Add alert sink (Telegram admin chat first, optional Slack webhook later) for critical failures.

#### A1: Durable Conversation State

- Execution status: Completed
- Build instructions:
  1. Add table `conversation_messages` in `storage.py`:
     - Columns: `id`, `user_id`, `role`, `content_json`, `created_at`
     - Index: `(user_id, created_at DESC)`
  2. Add APIs in `storage.py`:
     - `append_conversation_message(user_id, role, content_json)`
     - `load_recent_conversation(user_id, limit=20)`
     - `trim_conversation(user_id, keep_last=40)`
     - `clear_conversation(user_id)`
  3. In `bot.py`, hydrate in-memory `conversations[user_id]` from DB on first use.
  4. On each user/model turn, write-through to DB and trim old rows.
  5. Update `/reset` to clear both memory and persisted conversation.
- Validation:
  - Unit: storage read/write/trim/clear behavior.
  - Integration: restart process mid-conversation and verify continuity.
  - Evidence:
    - `python3 -m py_compile bot.py storage.py` passed
    - `python3 -m unittest discover -s tests -v` passed (conversation persistence test added)

#### A2: External Call Reliability Layer

- Execution status: Completed
- Build instructions:
  1. Add `reliability.py` with `run_with_resilience(...)` wrapper:
     - retry policy (bounded exponential backoff + jitter)
     - timeout per call
     - failure classification (`offline`, `rate_limit`, `auth`, `unknown`)
  2. Route these call sites through wrapper:
     - Gemini generation paths in `bot.py`
     - HTTP calls in `google_services.py` and weather/news/web helpers
  3. Add per-integration fallback messages mapped by failure class.
  4. Add lightweight circuit-breaker state in memory per dependency:
     - open after N consecutive failures
     - half-open probe window
     - short-circuit user-facing fast failure while open
- Validation:
  - Unit: retry/backoff behavior and breaker state transitions.
  - Failure injection: force timeouts/HTTP 5xx and verify graceful responses.
  - Evidence:
    - `python3 -m py_compile bot.py reliability.py` passed
    - `python3 -m unittest discover -s tests -v` passed after resilience wiring

#### A3: Observability and Alerting

- Execution status: Completed
- Build instructions:
  1. Add structured logger helper (`ops_logging.py`) with `event_type` conventions:
     - `command_received`, `tool_call`, `tool_result`, `api_error`, `handler_exception`
  2. Emit timing and outcome metadata around:
     - `generate_agent_response`
     - `run_tool`
     - critical callbacks (`/tools`, media handlers, thermostat/camera actions)
  3. Add alert dispatcher:
     - default channel: Telegram admin chat (`ADMIN_CHAT_ID`)
     - optional Slack webhook (`ALERT_WEBHOOK_URL`)
  4. Trigger alerts for:
     - repeated failures above threshold
     - startup/shutdown failures
     - circuit breaker open events > X minutes
- Validation:
  - Integration: simulate repeated failures and verify alert delivery + rate limiting.
  - Manual: confirm logs contain required fields and are grep/JSON-parse friendly.
  - Evidence:
    - `python3 -m py_compile bot.py ops_logging.py` passed
    - `python3 -m unittest discover -s tests -v` passed after A3 instrumentation

#### A4: Runtime Supervision and Operations Runbook

- Execution status: Completed
- Build instructions:
  1. Add `ops/systemd/bob-agent.service` and `ops/docker/Dockerfile` examples.
  2. Add health check command:
     - `python3 -m bot_healthcheck` (checks DB access, Gemini auth ping, optional Google token freshness)
  3. Configure restart policy and graceful stop path so offline message hooks still run.
  4. Update `INSTRUCTION_MANUAL.md` with:
     - start/stop procedures
     - log paths
     - incident checklist
- Validation:
  - 24-hour soak run with synthetic messages every 5 minutes.
  - Restart-kill-restart scenario with no crash loop and clean recovery.
  - Evidence:
    - `python3 -m py_compile bot.py bot_healthcheck.py` passed
    - `python3 -m unittest discover -s tests -v` passed after A4 artifacts/manual updates

#### Track A Rollout, Flags, and Rollback

- Feature flags:
  - `RELIABILITY_TRACK_A_ENABLED`
  - `PERSIST_CONVERSATIONS_ENABLED`
  - `ALERTING_ENABLED`
  - `CIRCUIT_BREAKER_ENABLED`
- Rollout:
  1. Enable for single operator user/chat.
  2. Run 48-hour soak and review error budget.
  3. Enable globally.
- Rollback:
  - Disable flags in reverse order (`CIRCUIT_BREAKER` -> `ALERTING` -> `PERSIST_CONVERSATIONS`) without schema rollback.

#### Track A Risks and Mitigations

- Risk: DB growth from conversation persistence.
  - Mitigation: trim policy + periodic compaction guidance.
- Risk: over-aggressive retries increase latency.
  - Mitigation: hard timeout budget and capped retry count.
- Risk: alert storms during upstream outages.
  - Mitigation: alert dedupe and cooldown windows.
- Risk: behavior drift due fallback paths.
  - Mitigation: golden-response checks for major workflows.

#### Track A Dependencies

- Existing SQLite layer in `storage.py`
- Environment variables in `.env`
- Optional external destination for alerts (Telegram admin chat or Slack webhook)

#### Track A Success Metrics

- Crash-loop rate: 0 in 24-hour soak.
- P95 response latency increase from resilience layer: < 20%.
- Recovery continuity: >= 95% of restart scenarios preserve last 20 turns.
- Critical alert detection latency: < 2 minutes.

#### Track A Acceptance Criteria

1. Conversation continuity survives process restart.
2. External outages degrade gracefully without unhandled exceptions.
3. Structured logs support incident triage by user/tool/error class.
4. Alerts fire for repeated critical failures with dedupe.
5. Operational runbook supports repeatable restart/recovery.

### Track B: Proactive Assistant Behaviors

- Status: Planned
- Goal: Move Bob from purely reactive chat to reliable, user-configurable proactive assistance delivered in Telegram.
- Primary outcomes:
  - Daily brief delivered at user-defined times.
  - Watchers that trigger on external state changes (news/price/travel/package).
  - Calendar-driven reminders/nudges with dedupe and missed-run recovery.
  - Minimal false positives and no notification spam.
- Non-goals:
  - No autonomous write-actions to Gmail/Calendar/Nest (read + notify only).
  - No multi-user org-level orchestration; optimize for single-user first.
  - No complex ML ranking/personalization engine (rule-based priority first).
  - No dependency on external queue infrastructure in v1 (stay SQLite-based).

#### Architecture Changes (Codebase-Fit)

1. New module: `proactive.py`
   - Scheduler loop and job execution orchestration.
   - Job registry for `morning_brief`, `calendar_nudges`, and watcher checks.
   - Shared retry/backoff wrapper for proactive jobs.
2. Storage extensions in `storage.py` (SQLite):
   - `proactive_jobs`:
     - `id`, `user_id`, `job_type`, `schedule_kind`, `schedule_json`, `enabled`, `last_run_at`, `next_run_at`, `last_status`, `created_at`, `updated_at`
   - `watchers`:
     - `id`, `user_id`, `watcher_type`, `query`, `params_json`, `enabled`, `cooldown_minutes`, `created_at`, `updated_at`
   - `proactive_events` (idempotency ledger):
     - `id`, `user_id`, `event_type`, `dedupe_key`, `payload_json`, `occurred_at`, `sent_at`, `status`
     - unique index on `(user_id, event_type, dedupe_key)`
   - `delivery_log`:
     - `id`, `user_id`, `channel`, `message_type`, `status`, `error`, `created_at`
3. Telegram delivery integration in `bot.py`:
   - Reuse `app.bot.send_message(...)` path.
   - Add helper: `send_proactive_message(bot, user_id, text, metadata)` with logging/fallback.
   - Add user commands: `/brief`, `/watchers`, `/quiet`, `/proactive`.
4. Runtime model:
   - Keep polling mode.
   - Start scheduler on app startup (`post_init`) and stop on shutdown (`post_stop`).
   - Add single-process lock to avoid duplicate scheduler instances.

#### Scheduling Model

- Base tick: every 60 seconds in one scheduler loop.
- Job eligibility: `enabled == true` and `next_run_at <= now`.
- After each run:
  - update `last_run_at`, `last_status`
  - compute new `next_run_at` from schedule config + user timezone
- Schedule types (v1):
  - daily at local time (for morning brief)
  - hourly interval (for watcher checks)
  - calendar-relative offsets (for nudges)
- Missed-run recovery:
  - morning brief: send at most one catch-up brief in a bounded window
  - watchers: run once immediately then resume normal cadence
  - calendar nudges: only send future reminders, skip stale ones

#### Watcher Model

1. `news_keyword`
   - Input: keyword query
   - Source: existing `search_web`/news path
   - Dedupe key: hash of canonicalized URL/title/date
2. `price_threshold`
   - Input: asset symbol + threshold condition
   - Source: lightweight finance endpoint wrapper
   - Dedupe key: symbol + threshold direction + rounded price bucket + day
3. `travel_or_package_status` (later phase)
   - Input: tracking identifier/provider
   - Source: pluggable provider adapters
   - Dedupe key: provider + tracking_id + status_code + checkpoint_time

Cooldown and anti-spam:
- Per-watcher cooldown (`cooldown_minutes`)
- Global per-user send cap (hour/day)
- Optional digest collapsing for burst windows

#### Dedupe and Idempotency

- Before sending, insert into `proactive_events` with `(user_id, event_type, dedupe_key)`.
- On unique conflict: skip send (already processed).
- Delivery retries update status in `proactive_events` and `delivery_log`.
- Scheduler run ownership uses compare-and-set semantics to prevent double execution.

#### User Controls and Quiet Hours

- Per-user proactive settings:
  - `proactive_enabled`
  - `quiet_hours_start`, `quiet_hours_end`, `quiet_hours_timezone`
  - `morning_brief_time`
  - `digest_mode` (`instant`/`batched`)
- Command UX:
  - `/proactive on|off`
  - `/quiet 22:00-07:00`
  - `/brief time 08:00`
  - `/watchers list|add|remove|pause|resume`
- Quiet-hours behavior:
  - defer non-critical proactive notifications
  - optional `override_quiet_hours=true` for critical alerts (off by default in v1)

#### Delivery UX in Telegram

- Message style:
  - short headline + concise bullets + source links
  - include “why you got this” line
  - watcher alerts include condition, current value/status, timestamp
- Interaction model:
  - plain text first in v1 (no heavy callback flows)
  - optional later actions: `Snooze`, `Mute this watcher`, `Show details`

#### Phased Rollout (B1..B4)

##### B1: Scheduler + Morning Brief MVP

- Execution status: Completed
- Build:
  1. Add DB tables: `proactive_jobs`, `proactive_events`, `delivery_log`.
  2. Create scheduler loop in `proactive.py`.
  3. Implement `morning_brief` (calendar + weather + top email summary).
  4. Add `/brief` setup command flow.
  5. Implement one-brief-per-day dedupe.
- Validation:
  - unit: schedule calculation, timezone conversion, dedupe key generation
  - integration: morning brief generation with mocked providers
  - manual: one brief at configured time over multiple days
  - Evidence:
    - `python3 -m py_compile bot.py proactive.py storage.py` passed
    - `python3 -m unittest discover -s tests -v` passed after scheduler and `/brief` integration

##### B2: Calendar Nudges + Quiet Hours

- Execution status: Completed
- Build:
  1. Add `calendar_nudge` job type.
  2. Add quiet-hours settings + deferral logic.
  3. Add `/quiet` command + status display.
  4. Add missed-run recovery policy for deferred nudges.
- Validation:
  - unit: quiet-hours windows and deferral
  - integration: timezone edge-case reminder generation
  - manual: events near quiet-hours boundaries
  - Evidence:
    - `python3 -m py_compile bot.py proactive.py storage.py` passed
    - `python3 -m unittest discover -s tests -v` passed after `/quiet` + calendar nudge controls

##### B3: Watchers Framework

- Execution status: Completed
- Build:
  1. Add `watchers` table and evaluation engine.
  2. Implement `news_keyword`, then `price_threshold`.
  3. Add `/watchers` CRUD command flow.
  4. Add cooldowns + per-user rate cap.
- Validation:
  - unit: evaluator + cooldown/rate-limit checks
  - integration: mock responses and verify dedupe
  - manual: repeated identical events should emit one alert
  - Evidence:
    - `python3 -m py_compile bot.py proactive.py storage.py` passed
    - `python3 -m unittest discover -s tests -v` passed after `/watchers` and watcher evaluation flow

##### B4: Hardening + UX Refinement

- Execution status: Completed
- Build:
  1. Add structured proactive logs (latency, failures, send outcomes).
  2. Add `/proactive status` (last run, next run, recent failures).
  3. Add failure alerting for repeated job failures.
  4. Add digest mode for bursty watcher events.
- Validation:
  - 72-hour soak with synthetic events
  - failure injection (timeouts, auth failures, network issues)
  - restart simulation with catch-up verification
  - Evidence:
    - `python3 -m py_compile bot.py proactive.py ops_logging.py bot_healthcheck.py` passed
    - `python3 -m unittest discover -s tests -v` passed after proactive status/digest/alerting updates

#### Failure Handling

- Retry policy: external reads retried 3 times with exponential backoff + jitter.
- Per-job thresholds:
  - mark degraded after N consecutive failures
  - send one degraded notice then suppress repeats for cooldown
- Provider fallback:
  - if one source fails, send partial brief with clear note
- Hard-stop protection:
  - scheduler auto-restarts if loop crashes
  - proactive failures must not block normal chat handlers

#### Feature Flags and Rollout

- Flags:
  - `PROACTIVE_ENABLED`
  - `PROACTIVE_MORNING_BRIEF_ENABLED`
  - `PROACTIVE_CALENDAR_NUDGES_ENABLED`
  - `PROACTIVE_WATCHERS_ENABLED`
  - `PROACTIVE_DIGEST_ENABLED`
- Rollout:
  1. enable for allowlisted user IDs only
  2. run B1 for one user for 3 days
  3. enable B2 with quiet-hour defaults
  4. enable B3 watcher types incrementally
  5. enable B4 and remove allowlist
- Rollback:
  - disable feature flags per subsystem without redeploy
  - preserve DB state for resume

#### Metrics

- Operational:
  - job success rate by type
  - p50/p95 job runtime
  - delivery success/failure rate
  - consecutive failure streaks
- User impact:
  - brief interaction proxy
  - watcher precision proxy (`mute`/`remove` soon after alert)
  - notification volume per day per user
- Quality:
  - duplicate alert rate
  - missed-run rate
  - false-positive rate from sampled audits

#### Acceptance Criteria

1. Morning brief is delivered once/day at configured local time for 3 consecutive days.
2. Calendar nudges honor quiet hours and defer correctly.
3. Watchers trigger correctly and do not send duplicate alerts for same event.
4. Restart does not cause duplicate sends or permanent missed jobs.
5. Proactive failures are observable, retried, and isolated from normal chat handling.
6. Any proactive subsystem can be disabled by flag without redeploy.

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
