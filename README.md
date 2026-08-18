# AI Voice Communication Assistant

A single-user AI voice English-speaking coach. This repo currently contains
**Phase 1 (Foundation)** through **Phase 7 (Production Hardening)** of the
full build: the FastAPI app skeleton, MongoDB connectivity, structured
logging, global error handling, security middleware, health/readiness
checks, a provider-agnostic AI abstraction (Gemini + NVIDIA), a global
settings API, a working voice pipeline (mic capture, VAD, real
speech-to-text, real text-to-speech), a continuous conversation loop over
WebSocket, live grammar corrections/vocabulary detection/scoring shown
turn-by-turn in the chat, a full learning dashboard, and now per-IP rate
limiting, WebSocket connection/frame-size safeguards, and full developer
documentation. See "What's next" below for the honest list of what's
still open even within Phase 7.

There is **no authentication** anywhere in this project by design — no
login, no JWT, no users collection. The app opens straight to its dashboard.

## What's implemented so far

### Phase 1 — Foundation
- FastAPI app with a `lifespan` handler that connects/disconnects MongoDB
- Async MongoDB access via Motor, plus index setup on startup
- Centralized settings (`app/core/config.py`) loaded from environment variables
- Structured JSON logging that redacts secrets automatically
- Global exception handling with a consistent error response shape
- Security/CORS/request-ID/body-size middleware
- `GET /api/health` (liveness) and `GET /api/health/ready` (readiness — checks
  Mongo connectivity and whether an AI provider key is configured)

### Phase 2 — AI Provider Layer
- `AIProvider` abstract interface (`app/services/ai/base_provider.py`) — the
  only contract conversation/analysis code (Phase 4+) will depend on
- `GeminiProvider` and `NvidiaProvider` — real REST implementations, each
  fully isolated behind the interface
- `ProviderFactory` — resolves a provider name to a concrete instance; the
  only place that imports the concrete provider classes
- `GET /api/ai/providers`, `GET /api/ai/models?provider=...`
- `GET /api/settings` / `PUT /api/settings` — the single global settings
  document (mother tongue, target language, difficulty, selected AI
  provider + model, voice/learning preferences)

### Phase 3 — Voice Pipeline
- **Frontend mic capture** (`frontend/js/voice.js`) — `getUserMedia` with
  echo cancellation / noise suppression / auto gain, a real-time client-side
  VAD loop (Web Audio API `AnalyserNode`, amplitude + silence-hangover
  timing) that decides when to stop recording without a network round trip,
  and the full `IDLE → LISTENING → PROCESSING → AI_SPEAKING` state machine
  from the spec (§17)
- **Audio normalization** (`app/services/voice/audio_processor.py`) —
  converts whatever the browser records (webm/opus, ogg, mp4...) into
  normalized 16kHz mono WAV via `ffmpeg`/`pydub`, so downstream VAD and STT
  always see one consistent format
- **Server-side VAD backstop** (`app/services/voice/voice_activity_detector.py`)
  — real WebRTC VAD (`webrtcvad`) double-checks every upload actually
  contains speech *before* spending an AI request on it (cost control,
  spec §47), and trims leading/trailing silence
- **Speech-to-text** (`app/services/voice/gemini_stt.py`) — Gemini's
  multimodal `generateContent` API, transcribes with per-language script
  (Tamil/Telugu/Hindi/Malayalam/Kannada mixed with English transcribes
  as spoken, not translated — spec §24)
- **Text-to-speech** (`app/services/voice/gemini_tts.py`) — Gemini's
  audio-output `generateContent` API, wrapped into playable WAV, with a
  speaking-speed control
- `POST /api/voice/vad-check`, `POST /api/voice/transcribe`,
  `POST /api/voice/synthesize` — standalone REST endpoints exercising the
  pipeline; Phase 4's WebSocket conversation loop will call the same
  service classes rather than duplicating this logic
- **A working browser console** (`frontend/index.html` + `css/` + `js/`) —
  not just a placeholder: a real mic button, live amplitude visualization,
  transcript panel (with Tamil-script rendering), and a text-to-speech test
  panel with a speaking-speed slider
- Tests run against **real** `ffmpeg` audio conversion and **real**
  `webrtcvad`/`espeak-ng`-synthesized speech (no mocking of the audio
  pipeline itself) — only the outbound Gemini HTTP calls are mocked, so
  the test suite never consumes API credits

### Phase 4 — Conversation Engine
- **`conversation_manager.py`** — orchestrates one full turn: normalize
  audio → server-side VAD gate → STT → build context → AI response → TTS,
  reusing the exact same Phase 2/3 service classes rather than a second
  implementation. The AI speaks first when a conversation is brand new
  (`generate_opening_message`)
- **`context_manager.py`** — builds the persona/system prompt (topic,
  difficulty, mother tongue) and windows conversation history to the most
  recent 12 messages before sending it to the AI provider, to control
  token usage (spec §27/§47)
- **`topic_manager.py`** — resolves the preset conversation topics
  (Job Interview, Travel Conversation, etc.) plus "Surprise Me" random
  selection (spec §25)
- **`conversation_repository.py`** — MongoDB CRUD for `conversations` and
  `conversation_messages`, each conversation keyed by its own UUID (no
  user accounts to scope by — spec §8)
- **Cost controls that actually run, not just config values** —
  `MAX_CONVERSATION_MINUTES` ends the conversation server-side once
  elapsed time is exceeded; `MAX_DAILY_AI_REQUESTS` raises a clean 429
  before any AI call once the daily assistant-message count is hit
- **`WS /ws/conversation/{conversation_id}`** — the real-time loop: the
  client sends one binary audio frame per recorded utterance (the same
  blob Phase 3's `VoiceController` already produces); the server replies
  with JSON status/transcript/assistant events plus a binary WAV frame for
  synthesized speech, implementing the full `IDLE → LISTENING →
  PROCESSING → AI_SPEAKING → LISTENING` loop from spec §17
- `POST/GET/DELETE /api/conversations`, `GET /api/conversations/{id}`,
  `GET /api/conversations/{id}/messages` — standard CRUD alongside the
  WebSocket loop
- **Frontend `conversation.js`** wires `VoiceController` (Phase 3) directly
  to the WebSocket — recorded utterances go out as binary frames, incoming
  JSON events update the chat transcript, incoming audio frames autoplay.
  `VoiceController` gained two small backward-compatible additions
  (`setExternalState`, `playAudioBlob`) rather than a rewrite, so the Phase
  3 standalone test panel keeps working unmodified. A new "Have a
  conversation" panel on the homepage (topic picker, Start/End button, chat
  thread) sits above the existing voice-pipeline test panel, both usable
  independently
- Frontend correctness was checked without a real browser (this sandbox
  can't download one) via a jsdom-based smoke test loading the actual
  `index.html`/JS files, checking every DOM selector the JS relies on
  actually exists, and simulating real button clicks — not just a syntax
  check
- **A real security fix found and closed this phase**: httpx's own
  request logger printed full outbound URLs at INFO level, and Gemini's
  REST API puts the API key in the URL query string — meaning every
  Gemini call was about to log the key in plaintext, in direct violation
  of this project's own logging policy (spec §45). Found via a live test
  with real credentials, fixed in `core/logging.py` (httpx/httpcore
  loggers raised to WARNING), verified fixed with a follow-up live call

### Phase 5 — Learning Analysis
- **One shared AI call per analyzed turn, not two**: grammar and
  vocabulary detection both parse the same `AIProvider.analyze_conversation`
  result (`ai_turn_analysis.py`) built in Phase 2, rather than each making
  their own call — `grammar_analyzer.py`/`vocabulary_analyzer.py` are pure
  parsing/validation of that shared result (filtering out no-op
  corrections and incomplete vocabulary entries), not separate AI calls
- **Fluency and confidence run on every turn for free** — `fluency_analyzer.py`
  and `confidence_analyzer.py` are local heuristics (filler-word density,
  speaking rate, response latency, answer length), no AI cost, clearly
  documented as heuristics rather than validated speech-science metrics.
  Confidence is explicitly labeled "AI-generated practice metric" per
  spec §35 — never presented as a psychological measurement
- **Pronunciation scoring is an honest stub, not a fake number**
  (`pronunciation_analyzer.py`): Gemini's transcription API doesn't expose
  phoneme-level confidence, so this returns `score: null` with an
  explanation rather than fabricating a plausible-looking score — real
  pronunciation assessment would need a provider that actually supports it
  (e.g. Azure Pronunciation Assessment), swapped in behind the same
  interface
- **`scoring_engine.py`** combines everything into per-turn scores and a
  rule-based (no extra AI call) end-of-conversation summary — "what you
  did well" / "improve next time" bullets generated from the score
  pattern, not another AI request
- Cost control ties into existing settings: grammar/vocabulary analysis is
  skipped entirely if both `show_corrections` and `show_vocabulary` are
  off in app_settings — zero extra AI cost when the learner doesn't want
  it
- WebSocket now emits `correction`, `vocabulary`, and `score_update`
  events (spec §32) in addition to Phase 4's events; the chat UI renders
  corrections/new-vocabulary as small annotation cards under each turn
  (matching the "✏️ Better" / "📚 New Word" mockup in spec §31) plus a
  live grammar/fluency/confidence/vocabulary score readout
- New `POST /api/conversations/{id}/analyze` — end-of-conversation summary
  (spec §34, §38), ends the conversation if still active, and folds the
  result into a rolling `learning_progress` aggregate (total
  conversations, running score averages, current streak) that Phase 6's
  dashboard will read
- **A known trade-off, not a hidden one**: grammar/vocabulary analysis
  runs *before* the turn's reply is sent back over the WebSocket, adding
  roughly one more AI round-trip of latency per turn when corrections are
  enabled. A non-blocking/fire-and-forget version is possible but adds
  real complexity (risk of the mic reopening before analysis events
  arrive); this was judged the simpler, more honest default given
  everything else already in Phase 4

### Phase 6 — Learning Dashboard
- **`GET /api/analytics/dashboard`** — total conversations, total speaking
  time, running score averages, vocabulary learned, current streak (spec
  §39), recent conversation history, and frequent mistake patterns (spec
  §40), all pure aggregation over data Phase 5 already stores — no AI
  calls, no extra cost
- **`GET /api/analytics/progress`** — one point per *analyzed* conversation
  (topic, date, all four scores), oldest-first, for the progress chart
- **`GET /api/vocabulary`, `DELETE /api/vocabulary/{id}`** — review and
  prune the vocabulary collection Phase 5 populates
- **`mistake_pattern_analyzer.py`** — buckets grammar corrections into
  categories (Past tense, Articles, Prepositions, Subject-verb agreement,
  Word choice, Other) by rule-based keyword matching on the correction's
  explanation text, per the "Frequent mistakes" example in spec §40.
  Deliberately not another AI call, and deliberately not dressed up as
  real grammatical-error-type classification — it's a best-effort bucket,
  documented as such, with unmatched corrections honestly landing in
  "Other" rather than force-fit into a category
- **A real idempotency bug found and fixed while building this**: calling
  `POST /conversations/{id}/analyze` a second time on an
  already-completed conversation was silently double-counting that
  conversation into the `learning_progress` running averages/totals.
  Fixed by only folding results into `learning_progress` the first time a
  conversation is analyzed (tracked via a `analysis_summary` field
  written onto the conversation document, which doubles as what the
  progress chart reads) — caught before shipping via a dedicated
  "analyze called twice" test, not found live
- **A new "Dashboard" tab** in the frontend, next to "Practice" — stat
  cards, a hand-rolled multi-series SVG line chart (grammar/fluency/
  confidence/vocabulary over time; deliberately no charting library
  dependency, consistent with keeping the frontend lightweight), a
  frequent-mistakes list, conversation history, and a vocabulary grid with
  working delete buttons. Data reloads every time the tab is opened, so
  it's never stale after finishing a conversation on the Practice tab
- Also this phase: `backend/Dockerfile` was restructured to build from
  the **repo root** (not `backend/`) so the image can bake in both
  `backend/` and `frontend/` and deploy as a single Render web service;
  added `render.yaml` and `docs/DEPLOYMENT.md` (GitHub push walkthrough +
  Render deploy walkthrough, including MongoDB Atlas setup since Render
  has no managed MongoDB)

### Phase 7 — Production Hardening
- **Per-IP rate limiting** (`app/core/rate_limit.py`) — an in-memory
  sliding-window limiter (`RATE_LIMIT_PER_MINUTE`, default 120/min),
  deliberately not Redis-backed (single-instance deployment, spec §63:
  don't add infrastructure that isn't earning its keep). Health checks
  and API docs are exempt so Render's own health probe never gets a
  spurious `429`. Verified live over real HTTP, not just in tests: hit a
  test limit of 3/min, got exactly three `200`s then `429`s, while
  `/api/health` stayed exempt through the same run
- **WebSocket safeguards**: a max audio-frame size (15MB, matching the
  REST `/api/voice/transcribe` limit) and a cap on concurrent connections
  (20) — a runaway/buggy client can no longer exhaust server memory via
  either an oversized frame or a reconnect loop. New connections beyond
  the cap are closed before the handshake completes rather than accepted
  and immediately dropped
- **`docs/DEVELOPER_GUIDE.md`** — architecture, the full
  request/conversation lifecycle, how to add a new AI/STT/TTS provider or
  conversation topic, MongoDB collection design, testing conventions, and
  a troubleshooting section built from failure modes actually hit while
  building this (not a generic template)
- **`docs/API.md`** — task-oriented endpoint reference with real example
  requests/responses, verified against the actual Pydantic schemas rather
  than written from memory
- **Honestly still open**: broader integration test coverage beyond the
  current suite, a closer look at rate-limit behavior under real
  concurrent load (only tested sequentially here), and the first genuine
  end-to-end run against real Gemini/NVIDIA credentials — this
  development environment has no outbound network access to either API,
  so every AI call in the test suite is mocked at the HTTP layer; the
  real integration should be exercised once deployed (see
  `docs/DEPLOYMENT.md`)

## Project structure

```
ai-voice-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, lifespan, router registration
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── health.py
│   │   │   │   ├── settings.py
│   │   │   │   ├── ai.py
│   │   │   │   ├── voice.py
│   │   │   │   ├── conversations.py    # CRUD + POST /analyze
│   │   │   │   ├── conversation_ws.py  # WS /ws/conversation/{id}
│   │   │   │   ├── vocabulary.py
│   │   │   │   └── analytics.py        # dashboard + progress
│   │   │   └── dependencies.py
│   │   ├── core/
│   │   │   ├── config.py      # Settings (env vars)
│   │   │   ├── logging.py     # Structured JSON logging
│   │   │   ├── exceptions.py  # AppError hierarchy + handlers
│   │   │   ├── middleware.py  # CORS, security headers, request IDs
│   │   │   └── rate_limit.py  # per-IP sliding-window rate limiting
│   │   ├── db/
│   │   │   ├── mongodb.py     # Motor client lifecycle
│   │   │   └── collections.py # Collection names + indexes
│   │   ├── schemas/
│   │   │   ├── settings.py
│   │   │   ├── voice.py
│   │   │   ├── conversation.py
│   │   │   ├── analysis.py
│   │   │   └── analytics.py
│   │   ├── services/
│   │   │   ├── ai/
│   │   │   │   ├── base_provider.py    # AIProvider interface
│   │   │   │   ├── gemini_provider.py
│   │   │   │   ├── nvidia_provider.py
│   │   │   │   └── provider_factory.py
│   │   │   ├── voice/
│   │   │   │   ├── speech_to_text.py       # STT interface
│   │   │   │   ├── text_to_speech.py       # TTS interface
│   │   │   │   ├── gemini_stt.py
│   │   │   │   ├── gemini_tts.py
│   │   │   │   ├── audio_processor.py      # format normalization (ffmpeg)
│   │   │   │   └── voice_activity_detector.py  # webrtcvad backstop
│   │   │   ├── conversation/
│   │   │   │   ├── conversation_manager.py # per-turn orchestration
│   │   │   │   ├── context_manager.py      # system prompt + history window
│   │   │   │   └── topic_manager.py        # preset topics + Surprise Me
│   │   │   ├── analysis/
│   │   │   │   ├── ai_turn_analysis.py     # shared AI call wrapper
│   │   │   │   ├── grammar_analyzer.py
│   │   │   │   ├── vocabulary_analyzer.py
│   │   │   │   ├── fluency_analyzer.py
│   │   │   │   ├── confidence_analyzer.py
│   │   │   │   ├── pronunciation_analyzer.py  # honest stub, no fake scores
│   │   │   │   ├── mistake_pattern_analyzer.py
│   │   │   │   └── scoring_engine.py
│   │   │   └── storage/
│   │   │       ├── settings_repository.py
│   │   │       ├── conversation_repository.py
│   │   │       ├── vocabulary_repository.py
│   │   │       ├── learning_progress_repository.py
│   │   │       └── analysis_repository.py
│   │   ├── models/ utils/  # scaffolding for later phases
│   ├── tests/  (20 files, 124 tests)
│   ├── requirements.txt
│   ├── Dockerfile              # repo-root build context, includes ffmpeg
│   └── .env.example
├── frontend/
│   ├── index.html              # Vaani console: Practice + Dashboard tabs
│   ├── css/global.css, voice.css, conversation.css, dashboard.css
│   └── js/api.js, voice.js, conversation.js, dashboard.js, app.js
├── docs/
│   ├── DEPLOYMENT.md            # GitHub + Render walkthrough
│   ├── DEVELOPER_GUIDE.md       # architecture, extension points, troubleshooting
│   └── API.md                   # endpoint reference with real examples
├── docker-compose.yml
├── render.yaml
├── .dockerignore
└── README.md
```

## Prerequisites

- Python 3.11+
- **`ffmpeg`** on PATH (audio format conversion) — already in the Docker
  image; install locally with `apt install ffmpeg` / `brew install ffmpeg`
- MongoDB (local, Docker, or Atlas)
- A **Gemini** API key — Phase 3's STT and TTS both use Gemini specifically
  (NVIDIA is still available for chat/analysis via Phase 2, but has no
  audio-capable endpoint wired up here)
- Optional (tests only): `espeak-ng` — lets the VAD test suite validate
  against genuine synthesized speech instead of only silence/tone; the
  suite skips that one test gracefully if it's not installed

## Local development

```bash
cd backend
cp .env.example .env
# edit .env: set MONGODB_URI and GEMINI_API_KEY

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then visit `http://localhost:8000/` — the **Practice** tab has the mic
button and full conversation loop; grant microphone permission, speak a
sentence, and it should transcribe. The **Dashboard** tab shows progress
stats, a score chart, frequent mistakes, and vocabulary once you've
completed and analyzed a few conversations.

Other useful URLs:

- `http://localhost:8000/api/health` / `/api/health/ready`
- `http://localhost:8000/api/ai/providers`, `/api/ai/models?provider=gemini`
- `http://localhost:8000/api/settings`
- `http://localhost:8000/docs` — interactive API docs, including the voice
  endpoints (try `/api/voice/vad-check` with a `.wav` file — it needs no
  API key, since VAD runs entirely locally)

## Running with Docker Compose (backend + MongoDB)

```bash
GEMINI_API_KEY=your-key docker compose up --build
```

## Deploying

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the full walkthrough:
pushing this repo to GitHub, setting up a free MongoDB Atlas cluster, and
deploying to Render using the included `render.yaml` blueprint and
`backend/Dockerfile` (build context is the repo root, so the image bakes
in both `backend/` and `frontend/` as one deployable service).

## Further documentation

- **[docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)** — architecture,
  the full request/conversation lifecycle, how to add a new AI/STT/TTS
  provider or conversation topic, MongoDB collection design, testing
  conventions, and a troubleshooting section for the failure modes
  actually hit while building this
- **[docs/API.md](docs/API.md)** — task-oriented endpoint reference with
  real example requests/responses; for the exhaustive always-in-sync
  reference, run the app and visit `/docs`

## Running tests

```bash
cd backend
python -m pytest -q
```

All 124 tests pass without a real MongoDB or Gemini/NVIDIA credentials —
MongoDB is faked with `mongomock-motor`, outbound HTTP to Gemini/NVIDIA is
intercepted with `respx`, but audio conversion (`ffmpeg`) and voice
activity detection (`webrtcvad`) run for real against synthetic (and,
where `espeak-ng` is available, genuinely synthesized-speech) audio.
Phases 4-6's suites stay intentionally leaner than Phase 3's exhaustive
provider-level coverage — pure-logic tests for the deterministic pieces
(topic/context selection, time/rate-limit rules, fluency/confidence
heuristics, score aggregation, streak logic, mistake categorization),
repository CRUD, REST CRUD, and one full WebSocket happy-path integration
test exercising the whole turn (transcript → correction → vocabulary →
score_update → audio), rather than an exhaustive edge-case matrix — the
underlying STT/TTS/VAD pieces everything else composes are already
covered thoroughly in Phase 3's suite. The frontend (Practice + Dashboard
tabs) is checked with a jsdom-based smoke test rather than a real browser
(unavailable in this build sandbox) — loading the actual HTML/JS,
confirming every DOM selector exists, and simulating real user
interactions including a full dashboard-tab-click → fetch → render →
chart-draw → delete flow against fake API responses.

## Environment variables

See `backend/.env.example` for the full list. Never commit a real `.env` —
it's already in `.gitignore`.

## What's next

Everything in the original spec's seven phases is now implemented in some
form. What's genuinely left, stated plainly rather than declared "done":

- **Real end-to-end verification against live Gemini/NVIDIA credentials.**
  This development environment has no outbound network access to either
  API — every AI call across the entire test suite is mocked at the HTTP
  layer (`respx`). The code has never made one real round-trip to Gemini
  or NVIDIA. Do this first after deploying (see `docs/DEPLOYMENT.md`).
- **Rate limiting under real concurrent load.** The limiter is verified
  correct sequentially (live curl test + unit tests), but not yet
  exercised under genuine concurrent traffic.
- **Broader integration coverage.** The suite favors one solid
  happy-path-plus-edge-cases per feature over exhaustive combinatorial
  coverage — reasonable for a single-user app, but worth expanding if this
  ever needs to support more than one concurrent user.
- **A settings UI for mother tongue / target language / difficulty.** The
  backend and `app_settings` fully support these (spec §23, §41); the
  frontend demo UI only wires up the default Tamil/English pair.

