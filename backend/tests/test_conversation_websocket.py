"""
Minimal integration test for the conversation WebSocket loop. Only the
outbound Gemini HTTP calls are mocked (respx); conversation state goes
through a real in-memory Mongo (mongomock-motor) and real ffmpeg/webrtcvad
audio processing, same as the rest of the suite.

Kept to two tests on purpose: one rejection path, one full happy path
covering conversation creation -> AI-speaks-first opening -> one real user
turn (transcript -> AI reply -> synthesized audio -> back to listening).
The silence-skips-the-AI-call behavior is already covered thoroughly at
the unit level in test_voice_routes.py against the exact same VAD gate
function conversation_manager reuses, so it isn't re-tested here.
"""
import base64
import io
import json
import wave

import numpy as np
import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from mongomock_motor import AsyncMongoMockClient

from app.core.config import get_settings
from app.db.mongodb import get_database
from app.main import app

_CHAT_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
_TTS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-preview-tts:generateContent"
)


def _make_speech_wav(duration_s: float = 1.0, sample_rate: int = 48000) -> bytes:
    """A simple tone -- enough amplitude for webrtcvad to register as speech."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    samples = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(samples.tobytes())
    return buffer.getvalue()


def _chat_or_stt_responder(request):
    """Gemini chat, Gemini STT, and Gemini turn-analysis all share this URL
    (same model) -- tell them apart by request content: STT includes inline
    audio data; analysis asks for grammar_score in its prompt; anything
    else is a normal chat reply."""
    body = json.loads(request.content)
    parts = body["contents"][0]["parts"]
    is_stt = any("inline_data" in p for p in parts)
    is_analysis = any("grammar_score" in p.get("text", "") for p in parts)

    if is_stt:
        text = '{"text": "I went to the office yesterday", "language": "en"}'
    elif is_analysis:
        text = (
            '{"grammar_score": 72, "fluency_score": 80, '
            '"corrections": [{"original": "I go office yesterday", '
            '"corrected": "I went to the office yesterday", '
            '"explanation": "Use past tense for completed actions."}], '
            '"new_words": [{"word": "discuss", "meaning": "talk about something", '
            '"example": "We discussed the project.", "translation": "", '
            '"difficulty": "beginner"}]}'
        )
    else:
        text = "That sounds interesting! What happened at the office?"
    return Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


def _tts_responder(request):
    pcm = np.zeros(8000, dtype=np.int16).tobytes()
    encoded = base64.b64encode(pcm).decode("ascii")
    return Response(
        200,
        json={
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inlineData": {"mimeType": "audio/L16;rate=16000", "data": encoded}}
                        ]
                    }
                }
            ]
        },
    )


@pytest.fixture
def ws_client():
    mongo_db = AsyncMongoMockClient()["test_db"]
    app.dependency_overrides[get_database] = lambda: mongo_db

    def fake_settings():
        return get_settings().model_copy(update={"gemini_api_key": "fake-key"})

    app.dependency_overrides[get_settings] = fake_settings

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.pop(get_database, None)
    app.dependency_overrides.pop(get_settings, None)

    # `with TestClient(app)` runs the real app lifespan, which connects a
    # *real* Motor client bound to that TestClient's event loop (even though
    # every route in this test uses the mongomock override above instead).
    # Once that loop closes, the leftover client reference is unusable and
    # breaks any later test that touches the global `mongodb` singleton
    # (e.g. /api/health/ready's ping) with "Event loop is closed" -- reset
    # it here so later tests see the same clean state they'd see if this
    # file had never run.
    from app.db.mongodb import mongodb as _mongodb_singleton

    _mongodb_singleton.client = None
    _mongodb_singleton.database = None


def test_websocket_rejects_unknown_conversation(ws_client):
    with ws_client.websocket_connect("/ws/conversation/does-not-exist") as ws:
        data = json.loads(ws.receive_text())
        assert data["type"] == "error"
        assert data["error_code"] == "NOT_FOUND"


@respx.mock
def test_websocket_full_turn_happy_path(ws_client):
    respx.post(_CHAT_URL).mock(side_effect=_chat_or_stt_responder)
    respx.post(_TTS_URL).mock(side_effect=_tts_responder)

    created = ws_client.post("/api/conversations", json={"topic": "Casual Conversation"})
    assert created.status_code == 200
    conversation_id = created.json()["id"]

    with ws_client.websocket_connect(f"/ws/conversation/{conversation_id}") as ws:
        # --- Opening turn: AI speaks first ---
        assert json.loads(ws.receive_text()) == {"type": "status", "status": "processing"}

        assistant_open = json.loads(ws.receive_text())
        assert assistant_open["type"] == "assistant"
        assert assistant_open["text"]

        audio_incoming = json.loads(ws.receive_text())
        assert audio_incoming["type"] == "audio_incoming"
        wav_bytes = ws.receive_bytes()
        assert wav_bytes.startswith(b"RIFF")

        assert json.loads(ws.receive_text()) == {"type": "status", "status": "listening"}

        # --- User turn: send real speech-shaped audio ---
        ws.send_bytes(_make_speech_wav())

        assert json.loads(ws.receive_text()) == {"type": "status", "status": "processing"}

        transcript = json.loads(ws.receive_text())
        assert transcript == {
            "type": "transcript",
            "speaker": "user",
            "text": "I went to the office yesterday",
            "language": "en",
        }

        assistant_reply = json.loads(ws.receive_text())
        assert assistant_reply["type"] == "assistant"
        assert assistant_reply["text"]

        correction = json.loads(ws.receive_text())
        assert correction == {
            "type": "correction",
            "original": "I go office yesterday",
            "corrected": "I went to the office yesterday",
            "explanation": "Use past tense for completed actions.",
        }

        vocabulary = json.loads(ws.receive_text())
        assert vocabulary["type"] == "vocabulary"
        assert vocabulary["word"] == "discuss"

        score_update = json.loads(ws.receive_text())
        assert score_update["type"] == "score_update"
        assert score_update["grammar"] == 72
        assert score_update["pronunciation"] is None  # honestly unsupported, see pronunciation_analyzer

        audio_incoming_2 = json.loads(ws.receive_text())
        assert audio_incoming_2["type"] == "audio_incoming"
        ws.receive_bytes()

        assert json.loads(ws.receive_text()) == {"type": "status", "status": "listening"}

    # The turn should have been persisted.
    messages = ws_client.get(f"/api/conversations/{conversation_id}/messages").json()
    speakers = [m["speaker"] for m in messages]
    assert speakers == ["assistant", "user", "assistant"]
