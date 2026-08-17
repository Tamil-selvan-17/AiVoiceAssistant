"""
Minimal tests for the conversation repository, against an in-memory Mongo
(mongomock-motor) -- no real MongoDB needed.
"""
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.services.storage import conversation_repository as repo


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


@pytest.mark.asyncio
async def test_create_and_get_conversation(db):
    created = await repo.create_conversation(
        db, {"topic": "Casual Conversation", "difficulty": "beginner",
             "mother_language": "Tamil", "target_language": "English",
             "ai_provider": "gemini", "ai_model": ""}
    )
    assert created["status"] == "active"
    assert created["ended_at"] is None

    fetched = await repo.get_conversation(db, created["_id"])
    assert fetched["topic"] == "Casual Conversation"


@pytest.mark.asyncio
async def test_get_missing_conversation_returns_none(db):
    assert await repo.get_conversation(db, "does-not-exist") is None


@pytest.mark.asyncio
async def test_end_conversation_sets_status_and_duration(db):
    created = await repo.create_conversation(db, {"topic": "Casual Conversation"})
    ended = await repo.end_conversation(db, created["_id"])
    assert ended["status"] == "completed"
    assert ended["duration_seconds"] is not None
    assert ended["ended_at"] is not None


@pytest.mark.asyncio
async def test_add_and_get_messages_in_order(db):
    created = await repo.create_conversation(db, {"topic": "Casual Conversation"})
    await repo.add_message(db, created["_id"], "assistant", "Hi there!", "en")
    await repo.add_message(db, created["_id"], "user", "Hello", "en")

    messages = await repo.get_messages(db, created["_id"])
    assert [m["speaker"] for m in messages] == ["assistant", "user"]


@pytest.mark.asyncio
async def test_delete_conversation_removes_messages_too(db):
    created = await repo.create_conversation(db, {"topic": "Casual Conversation"})
    await repo.add_message(db, created["_id"], "user", "Hello", "en")

    deleted = await repo.delete_conversation(db, created["_id"])
    assert deleted is True
    assert await repo.get_conversation(db, created["_id"]) is None
    assert await repo.get_messages(db, created["_id"]) == []


@pytest.mark.asyncio
async def test_count_assistant_messages_today(db):
    created = await repo.create_conversation(db, {"topic": "Casual Conversation"})
    assert await repo.count_assistant_messages_today(db) == 0

    await repo.add_message(db, created["_id"], "assistant", "Hi", "en")
    await repo.add_message(db, created["_id"], "user", "Hello", "en")
    await repo.add_message(db, created["_id"], "assistant", "How are you?", "en")

    assert await repo.count_assistant_messages_today(db) == 2
