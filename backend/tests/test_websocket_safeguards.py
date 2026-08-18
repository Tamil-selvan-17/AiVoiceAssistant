"""
Tests for the WebSocket-specific safeguards added in Phase 7: a max
uploaded-audio-frame size, and a cap on concurrent connections. Separate
from test_conversation_websocket.py since these are guard-rail tests, not
conversation-flow tests.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

import app.api.routes.conversation_ws as ws_module
from app.core.config import get_settings
from app.db.mongodb import get_database
from app.main import app
from app.services.storage import conversation_repository as repo


@pytest.fixture
def ws_client():
    mongo_db = AsyncMongoMockClient()["test_db"]
    app.dependency_overrides[get_database] = lambda: mongo_db

    def fake_settings():
        return get_settings().model_copy(update={"gemini_api_key": "fake-key"})

    app.dependency_overrides[get_settings] = fake_settings

    with TestClient(app) as client:
        yield client, mongo_db

    app.dependency_overrides.pop(get_database, None)
    app.dependency_overrides.pop(get_settings, None)

    from app.db.mongodb import mongodb as _mongodb_singleton

    _mongodb_singleton.client = None
    _mongodb_singleton.database = None


def _seed_conversation_with_history(mongo_db):
    """A conversation with at least one message so the WS skips the
    AI-generated opening turn -- these tests only care about the
    guard-rail paths, not the conversation flow itself."""
    loop = asyncio.get_event_loop()
    conversation = loop.run_until_complete(
        repo.create_conversation(mongo_db, {"topic": "Casual Conversation", "ai_provider": "gemini"})
    )
    loop.run_until_complete(repo.add_message(mongo_db, conversation["_id"], "assistant", "Hi!", "en"))
    return conversation


def test_oversized_audio_frame_is_rejected(ws_client):
    client, mongo_db = ws_client
    conversation = _seed_conversation_with_history(mongo_db)

    with client.websocket_connect(f"/ws/conversation/{conversation['_id']}") as ws:
        assert json.loads(ws.receive_text()) == {"type": "status", "status": "listening"}

        oversized = b"0" * (ws_module._MAX_WS_AUDIO_BYTES + 1)
        ws.send_bytes(oversized)

        error = json.loads(ws.receive_text())
        assert error["type"] == "error"
        assert error["error_code"] == "PAYLOAD_TOO_LARGE"

        assert json.loads(ws.receive_text()) == {"type": "status", "status": "listening"}


def test_connection_limit_rejects_beyond_cap(ws_client, monkeypatch):
    client, mongo_db = ws_client
    monkeypatch.setattr(ws_module, "_MAX_CONCURRENT_CONNECTIONS", 1)
    conversation = _seed_conversation_with_history(mongo_db)

    with client.websocket_connect(f"/ws/conversation/{conversation['_id']}") as first_ws:
        # First connection occupies the only available slot.
        assert json.loads(first_ws.receive_text()) == {"type": "status", "status": "listening"}

        # A second, simultaneous connection should be rejected outright --
        # the server closes it before completing a normal handshake.
        with pytest.raises(Exception):
            with client.websocket_connect(f"/ws/conversation/{conversation['_id']}") as second_ws:
                second_ws.receive_text()
