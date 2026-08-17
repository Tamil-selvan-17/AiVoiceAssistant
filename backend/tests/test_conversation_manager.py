"""
Minimal tests for conversation_manager's business rules (time limit, daily
rate limit) that don't require mocking the AI/voice pipeline. Full
happy-path pipeline coverage lives in test_conversation_websocket.py.
"""
from datetime import datetime, timedelta, timezone

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.core.config import Settings
from app.core.exceptions import RateLimitError
from app.services.conversation import conversation_manager as manager
from app.services.storage import conversation_repository as repo


def _settings(**overrides) -> Settings:
    base = dict(
        GEMINI_API_KEY="fake-key",
        MAX_CONVERSATION_MINUTES=30,
        MAX_DAILY_AI_REQUESTS=100,
        AI_REQUEST_TIMEOUT_SECONDS=5,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_conversation_not_expired_when_within_limit():
    conversation = {"started_at": datetime.now(timezone.utc) - timedelta(minutes=5)}
    assert manager.is_conversation_expired(conversation, max_minutes=30) is False


def test_conversation_expired_when_elapsed_exceeds_limit():
    conversation = {"started_at": datetime.now(timezone.utc) - timedelta(minutes=31)}
    assert manager.is_conversation_expired(conversation, max_minutes=30) is True


@pytest.mark.asyncio
async def test_handle_user_turn_ends_conversation_past_time_limit():
    db = AsyncMongoMockClient()["test_db"]
    conversation = await repo.create_conversation(db, {"topic": "Casual Conversation", "ai_provider": "gemini"})
    # Backdate started_at past the limit.
    await db["conversations"].update_one(
        {"_id": conversation["_id"]},
        {"$set": {"started_at": datetime.now(timezone.utc) - timedelta(minutes=31)}},
    )
    conversation = await repo.get_conversation(db, conversation["_id"])

    result = await manager.handle_user_turn(
        db, _settings(MAX_CONVERSATION_MINUTES=30), conversation, raw_audio=b"irrelevant"
    )

    assert result.conversation_ended is True
    assert result.end_reason == "time_limit"
    ended = await repo.get_conversation(db, conversation["_id"])
    assert ended["status"] == "completed"


@pytest.mark.asyncio
async def test_handle_user_turn_raises_when_daily_limit_reached():
    db = AsyncMongoMockClient()["test_db"]
    conversation = await repo.create_conversation(db, {"topic": "Casual Conversation", "ai_provider": "gemini"})
    await repo.add_message(db, conversation["_id"], "assistant", "reply 1", "en")
    await repo.add_message(db, conversation["_id"], "assistant", "reply 2", "en")

    with pytest.raises(RateLimitError):
        await manager.handle_user_turn(
            db,
            _settings(MAX_DAILY_AI_REQUESTS=2),
            conversation,
            raw_audio=b"irrelevant",
        )
