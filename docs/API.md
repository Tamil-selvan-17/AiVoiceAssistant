# API Reference

For the exhaustive, always-in-sync reference (every field, every status
code), run the app and visit `/docs` (Swagger UI) or `/redoc` — these are
generated directly from the code and can't drift out of date the way this
file can. What follows is a task-oriented overview: what each endpoint is
for and a representative example, not a field-by-field spec.

No authentication anywhere — every endpoint below is open. See the root
`README.md` for why.

## Error shape

Every error response, regardless of endpoint, looks like:

```json
{
  "success": false,
  "message": "Human-readable, safe to show the user",
  "error_code": "STABLE_UPPER_SNAKE_CASE_CODE"
}
```

Common `error_code` values: `NOT_FOUND`, `VALIDATION_ERROR`,
`RATE_LIMIT_EXCEEDED`, `DAILY_LIMIT_REACHED`, `AI_PROVIDER_ERROR`,
`AI_PROVIDER_NOT_CONFIGURED`, `VOICE_PROCESSING_ERROR`, `PAYLOAD_TOO_LARGE`,
`UNKNOWN_AI_PROVIDER`.

## Health

```
GET /api/health          -- liveness, always 200 if the process is up
GET /api/health/ready     -- readiness: checks MongoDB + AI provider config
```

```json
// GET /api/health/ready
{
  "status": "ready",
  "checks": {
    "mongodb": "ok",
    "ai_provider_configured": true,
    "gemini_configured": true,
    "nvidia_configured": false
  }
}
```

## Settings

```
GET /api/settings
PUT /api/settings
```

Single global document (no per-user scoping). `PUT` is a partial update —
omitted fields are left unchanged.

```json
// PUT /api/settings  { "ai_provider": "nvidia", "difficulty": "advanced" }
// -> 200, full updated document back
```

## AI providers

```
GET /api/ai/providers                  -- which providers have credentials configured
GET /api/ai/models?provider=gemini     -- available models for a provider
```

## Voice (standalone, outside a conversation)

```
POST /api/voice/vad-check     -- multipart file upload, no AI cost: is there speech in this clip?
POST /api/voice/transcribe    -- multipart file upload -> transcript (costs one AI call unless silent)
POST /api/voice/synthesize    -- {"text": "...", "speaking_speed": 1.0} -> raw WAV bytes
```

```bash
curl -F "file=@clip.wav;type=audio/wav" http://localhost:8000/api/voice/vad-check
# {"contains_speech": true, "speech_ratio": 0.87, "duration_seconds": 2.1}
```

## Conversations

```
POST   /api/conversations                    -- create (all fields optional, fall back to app_settings)
GET    /api/conversations                     -- list, newest first
GET    /api/conversations/{id}
GET    /api/conversations/{id}/messages
DELETE /api/conversations/{id}
POST   /api/conversations/{id}/analyze        -- end-of-conversation summary; ends it if still active
```

```json
// POST /api/conversations  {"topic": "Job Interview"}
{
  "id": "8d6e7a6b-1234-4567-8901-123456789abc",
  "topic": "Job Interview",
  "difficulty": "beginner",
  "mother_language": "Tamil",
  "target_language": "English",
  "ai_provider": "gemini",
  "ai_model": "",
  "started_at": "2026-08-18T09:00:00Z",
  "ended_at": null,
  "duration_seconds": null,
  "status": "active"
}
```

```json
// POST /api/conversations/{id}/analyze
{
  "conversation_id": "8d6e7a6b-...",
  "topic": "Job Interview",
  "duration_seconds": 420,
  "message_count": 8,
  "overall_score": 82,
  "fluency_score": 80,
  "confidence_score": 78,
  "grammar_score": 88,
  "vocabulary_score": 75,
  "pronunciation_score": null,
  "pronunciation_note": "Pronunciation scoring isn't available yet -- ...",
  "filler_word_count": 3,
  "new_words_learned": 2,
  "what_went_well": ["Strong grammar accuracy", "Learned 2 new words"],
  "improve_next_time": ["Practice speaking a little more steadily"]
}
```

## Conversation WebSocket

```
WS /ws/conversation/{id}
```

Not a REST endpoint — see `app/api/routes/conversation_ws.py`'s module
docstring for the full wire protocol (event types, when binary frames
appear). Summary: client sends one binary audio frame per recorded
utterance; server replies with a sequence of JSON events
(`status`/`transcript`/`assistant`/`correction`/`vocabulary`/
`score_update`/`audio_incoming`/`error`) plus a binary WAV frame for
synthesized speech.

## Vocabulary

```
GET    /api/vocabulary           -- all stored words, most recent first
DELETE /api/vocabulary/{id}
```

## Analytics (dashboard)

```
GET /api/analytics/dashboard     -- totals, averages, streak, recent history, frequent mistakes
GET /api/analytics/progress      -- one point per analyzed conversation, for charting
```

```json
// GET /api/analytics/dashboard
{
  "total_conversations": 5,
  "total_speaking_seconds": 2100,
  "avg_fluency": 79.4,
  "avg_confidence": 75.0,
  "avg_grammar": 84.2,
  "avg_vocabulary": 71.8,
  "vocabulary_learned_count": 12,
  "current_streak_days": 3,
  "recent_conversations": [ /* ConversationHistoryItem[] */ ],
  "frequent_mistakes": [
    {"category": "Past tense", "count": 4, "tip": "Review regular/irregular past tense verb forms."}
  ]
}
```

## Rate limiting

All endpoints above except `/api/health*`, `/docs`, `/redoc`,
`/openapi.json` are subject to a per-IP sliding-window limit
(`RATE_LIMIT_PER_MINUTE`, default 120/min). Exceeding it returns `429`
with `error_code: "RATE_LIMIT_EXCEEDED"` and a `Retry-After` header.
