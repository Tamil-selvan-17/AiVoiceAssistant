# Developer Guide

This is the deeper, code-level companion to the root `README.md` —
written for whoever (including future-you) needs to extend or debug this
project rather than just run it.

## Architecture

Three independent layers, each depending only on the interface below it:

```
Voice Layer          AI Engine Layer         Learning Layer
STT / TTS / VAD       Gemini/NVIDIA           Grammar / Vocabulary
Audio processing      via ProviderFactory     Fluency / Confidence
                                               Pronunciation (stub)
        \                    |                      /
         \                   |                     /
          ------------- Conversation Manager -------
                             |
                          MongoDB
```

The **Conversation Manager** (`app/services/conversation/conversation_manager.py`)
is the only place that calls into all three layers for a single turn. The
**WebSocket route** (`app/api/routes/conversation_ws.py`) is protocol
translation only — it never talks to Gemini, MongoDB, or audio processing
directly; it calls the Conversation Manager and turns the result into
WebSocket events.

This matters for anyone adding a feature: if you're tempted to add logic
to the WebSocket route or a REST route beyond "parse request → call a
service → format response", that logic almost certainly belongs in a
service module instead, so it isn't duplicated between the REST endpoints
and the WebSocket loop.

## Project structure

See the tree in `README.md` — kept up to date there rather than
duplicated here.

## Application flow (a full conversation, end to end)

1. `POST /api/conversations` — `topic_manager.resolve_topic()` picks a
   topic (or honors the one given), unset fields fall back to
   `app_settings`, `conversation_repository.create_conversation()` inserts
   the document.
2. Client opens `WS /ws/conversation/{id}`. Since there are no messages
   yet, `conversation_manager.generate_opening_message()` runs: builds a
   system prompt (`context_manager.build_system_prompt()`), asks the AI
   provider for an opening line, synthesizes it with TTS, sends it back.
3. Client records the user's reply (mic → VAD → `MediaRecorder`), sends
   the blob as one binary WS frame.
4. `conversation_manager.handle_user_turn()` runs the full turn: time/rate
   limit checks → `audio_processor.normalize_to_wav()` → server-side
   `voice_activity_detector` gate → `gemini_stt.transcribe()` → build
   context (`context_manager.build_recent_messages()`, capped at
   `MAX_RECENT_MESSAGES`) → AI reply → TTS → (if enabled)
   `ai_turn_analysis.run_ai_turn_analysis()` → grammar/vocabulary/fluency/
   confidence/pronunciation analyzers → `scoring_engine.compute_turn_scores()`
   → persist everything.
5. The WS route turns that `TurnResult` into a sequence of events:
   `transcript` → `correction`×N → `vocabulary`×N → `score_update` →
   `audio_incoming` + binary WAV → `status: listening`.
6. Loop continues until the client disconnects or `MAX_CONVERSATION_MINUTES`
   is hit (which ends the conversation server-side, sends `status: ended`).
7. Client calls `POST /api/conversations/{id}/analyze` — aggregates all the
   per-turn `conversation_analysis` docs into a summary
   (`scoring_engine.build_conversation_summary()`), writes it onto the
   conversation document (`analysis_summary` field — this is what backs
   the dashboard's progress chart), and folds it into the rolling
   `learning_progress` document exactly once (guarded so calling
   `/analyze` twice doesn't double-count).

## Voice flow

See `README.md`'s Phase 3 section for the pipeline description. Code-level
entry points:
- `app/services/voice/audio_processor.py` — `normalize_to_wav()` (any
  browser format → 16kHz mono WAV via ffmpeg/pydub), `wav_to_pcm16()`
- `app/services/voice/voice_activity_detector.py` — `VoiceActivityDetector.analyze()`
  wraps `webrtcvad`
- `app/services/voice/gemini_stt.py`, `gemini_tts.py` — concrete
  implementations of the interfaces below

## WebSocket flow

See the module docstring in `app/api/routes/conversation_ws.py` for the
exact wire protocol (event types, binary frame ordering). Two safeguards
worth knowing about if you're debugging connection issues:
- `_MAX_WS_AUDIO_BYTES` (15MB) — an oversized binary frame gets a
  `PAYLOAD_TOO_LARGE` error event, not a dropped connection
- `_MAX_CONCURRENT_CONNECTIONS` (20) — beyond this, new connections are
  closed with code `1013` before the handshake completes

## AI provider flow

`ProviderFactory.create(provider_name, settings, model_override)` is the
**only** place that imports `GeminiProvider`/`NvidiaProvider` directly.
Everything else — `conversation_manager`, the analysis modules — depends
only on the `AIProvider` abstract interface (`app/services/ai/base_provider.py`).

### Adding a new AI provider

1. Create `app/services/ai/your_provider.py` implementing `AIProvider`'s
   four methods (`generate_response`, `analyze_conversation`,
   `list_models`, `is_configured`). Look at `nvidia_provider.py` as the
   simpler of the two existing examples (Gemini's is more involved because
   it also backs STT).
2. Add it to `ProviderFactory.create()` and `SUPPORTED_PROVIDERS` in
   `provider_factory.py`.
3. Add its API key/model/base-url fields to `app/core/config.py` and
   `.env.example`.
4. Add provider-level tests mirroring `tests/test_ai_provider.py` (mock
   HTTP with `respx`, never call the real API in tests).

### Adding a new STT or TTS provider

Same shape: implement `SpeechToText`/`TextToSpeech`
(`app/services/voice/speech_to_text.py` / `text_to_speech.py`), then wire
it in wherever `GeminiSpeechToText`/`GeminiTextToSpeech` are currently
instantiated directly (`conversation_manager.py`, `app/api/routes/voice.py`).
There's no factory for these yet since only one implementation of each
exists — if you add a second, promote this into a
`provider_factory.py`-style pattern matching the AI layer, rather than an
if/elif scattered across call sites.

## MongoDB design

No `users` collection — this is single-user, no auth. Collections
(`app/db/collections.py`):

| Collection | Purpose | Key relationships |
|---|---|---|
| `conversations` | One doc per conversation, UUID `_id` | `analysis_summary` field written by `/analyze` |
| `conversation_messages` | One doc per turn (user or assistant) | `conversation_id` FK |
| `conversation_analysis` | One doc per *analyzed user turn* | `conversation_id` FK |
| `vocabulary` | One doc per unique word (case-insensitive) | `review_count` increments on repeats |
| `learning_progress` | Single doc, `_id: "default"` | Rolling aggregate, updated once per completed conversation |
| `app_settings` | Single doc, `_id: "default"` | Global settings (spec §9) |

No relational joins — everything is fetched by `conversation_id` and
combined in Python, which is fine at this scale (single user, bounded
conversation counts) and avoids MongoDB aggregation-pipeline complexity
that isn't earning its keep yet.

## Scoring engine

`app/services/analysis/scoring_engine.py` is deliberately rule-based, not
another AI call — see the module docstring for the reasoning. If you want
to change how a score is calculated, that's the one file to touch; if you
want to change what counts as a "mistake pattern", see
`mistake_pattern_analyzer.py`'s keyword tables instead.

**Pronunciation is a real stub** (`pronunciation_analyzer.py`): it always
returns `score: None`. This isn't a bug — see that file's docstring. To
make it real, swap in an STT/analysis provider that exposes phoneme-level
confidence (e.g. Azure Pronunciation Assessment) and change
`analyze_pronunciation()` to use it; nothing downstream needs to change
since callers already handle `score: None` as a valid state.

## Adding a new language

Mother tongue / target language are free-text fields on `app_settings` and
per-conversation (spec §23) — there's no hardcoded language enum to edit.
What *is* hardcoded:
- The frontend's language picker options, if you add a settings UI for it
  (currently only the default Tamil/English pair is wired into the demo UI)
- Nothing in `gemini_stt.py` needs to change for a new mother tongue — its
  prompt already handles arbitrary mixed-language input generically

## Adding a new conversation type

Add the topic string to `CONVERSATION_TOPICS` in `app/schemas/conversation.py`
and to the `<select>` options in `frontend/index.html`. That's it — the
system prompt (`context_manager.build_system_prompt()`) takes the topic as
a free-text parameter, no per-topic code branch needed.

## Error handling

`app/core/exceptions.py` defines the `AppError` hierarchy. Every handled
error returns `{"success": false, "message": ..., "error_code": ...}` —
never a raw stack trace (see `register_exception_handlers()`). When adding
a new failure mode, prefer raising one of the existing `AppError`
subclasses (or a new one following the same pattern) over an ad-hoc
`HTTPException`, so the response shape stays consistent.

## Logging

`app/core/logging.py` — structured JSON, one line per log entry.
**Important**: `httpx`/`httpcore` loggers are explicitly raised to
`WARNING` in `configure_logging()`. This is load-bearing, not incidental —
Gemini's REST API puts the API key in the URL query string, and httpx logs
full request URLs at `INFO`. If you ever see `httpx`/`httpcore` logging
re-enabled at `INFO` in a future change, that's a credential leak
regression; this was found and fixed live during development (see the
Phase 4 section of `README.md`).

## Testing

```bash
cd backend && python -m pytest -q
```

Conventions used throughout the suite:
- **Never** call the real Gemini/NVIDIA APIs — mock with `respx`
- **Never** require a real MongoDB — use `mongomock-motor` via a
  `get_database` dependency override
- Audio/VAD tests run **real** `ffmpeg`/`webrtcvad` against synthetic (and,
  where `espeak-ng` is installed, genuinely synthesized-speech) audio —
  the audio pipeline itself is not mocked, only the network calls are
- WebSocket tests use `fastapi.testclient.TestClient` (synchronous,
  triggers real app lifespan) rather than `httpx.AsyncClient` — this is
  the one place in the suite that needs it, since async WS testing over
  `ASGITransport` isn't well supported

## Docker

`backend/Dockerfile`'s build context is the **repo root**, not `backend/`
— it copies both `backend/app` and `frontend/` so the image is a complete,
single deployable service. If you add new top-level directories that
should ship in the image, add a `COPY` line for them; if you add
directories that shouldn't ship (build artifacts, docs), add them to
`.dockerignore`.

## Render deployment

See `docs/DEPLOYMENT.md` for the full walkthrough. Quick reference:
- `render.yaml` is the Blueprint — secrets are `sync: false` (Render
  prompts for them, they never touch the file/git history)
- Health check path: `/api/health`
- `FRONTEND_DIR=/app/frontend` is set in the Dockerfile so `main.py`'s
  static-file mount finds the frontend regardless of Render's working
  directory

## Troubleshooting

**"MongoDB has not been initialized yet" / readiness shows `mongodb: unavailable`**
Check `MONGODB_URI`. Locally, make sure Mongo is actually running
(`docker compose up` starts one, or point at Atlas). This project doesn't
crash on startup if Mongo is unreachable (by design — see
`connect_to_mongo()`'s docstring), so the process staying up isn't itself
a sign of a working DB connection; check `/api/health/ready`.

**A Gemini call returns a generic 502 `AI_PROVIDER_ERROR`**
The real error (status code, response body) is logged server-side but
never returned to the client (see `core/exceptions.py`). Check the server
logs for the actual `gemini_request_failed`/`stt_request_failed`/etc. log
line with the real status code.

**WebSocket connects but nothing happens after sending audio**
Check `ffmpeg` is installed and on `PATH` — `normalize_to_wav()` shells
out to it. Locally: `which ffmpeg`. In Docker: already included in the
base image.

**Rate limited unexpectedly (`429 RATE_LIMIT_EXCEEDED`)**
`RATE_LIMIT_PER_MINUTE` (default 120) is per-IP, sliding 60s window,
across all non-exempt endpoints (see `app/core/rate_limit.py`'s
`_EXEMPT_PREFIXES`). If you're testing with a script hammering the API,
either raise the env var or slow the script down — this isn't meant to
throttle normal single-user usage.

**Tests fail with "Event loop is closed"**
This happens if a test uses `fastapi.testclient.TestClient` (which runs
the real app lifespan, creating a real Motor client bound to that test's
event loop) without resetting the global `app.db.mongodb.mongodb`
singleton afterward. See the `ws_client` fixture in
`test_conversation_websocket.py` for the pattern — it explicitly nulls
`mongodb.client`/`mongodb.database` in teardown. Copy that pattern for any
new test that needs `TestClient`.
