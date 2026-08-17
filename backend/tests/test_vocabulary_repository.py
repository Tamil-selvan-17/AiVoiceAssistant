"""Tests for the vocabulary repository, against an in-memory Mongo."""
import pytest
from mongomock_motor import AsyncMongoMockClient

from app.services.storage import vocabulary_repository as vocab_repo


@pytest.fixture
def db():
    return AsyncMongoMockClient()["test_db"]


@pytest.mark.asyncio
async def test_upsert_creates_new_word(db):
    doc = await vocab_repo.upsert_word(db, "Discuss", "talk about something", difficulty="intermediate")
    assert doc["word"] == "discuss"  # normalized to lowercase
    assert doc["review_count"] == 1


@pytest.mark.asyncio
async def test_upsert_repeated_word_increments_review_count_not_duplicates(db):
    await vocab_repo.upsert_word(db, "discuss", "talk about something")
    await vocab_repo.upsert_word(db, "Discuss", "talk about something")  # different casing, same word
    doc = await vocab_repo.upsert_word(db, "DISCUSS", "talk about something")

    assert doc["review_count"] == 3
    assert await vocab_repo.count_vocabulary(db) == 1  # still one document, not three


@pytest.mark.asyncio
async def test_list_vocabulary_returns_stored_words(db):
    await vocab_repo.upsert_word(db, "discuss", "talk about something")
    await vocab_repo.upsert_word(db, "confident", "feeling sure of yourself")
    words = await vocab_repo.list_vocabulary(db)
    assert {w["word"] for w in words} == {"discuss", "confident"}


@pytest.mark.asyncio
async def test_delete_word(db):
    doc = await vocab_repo.upsert_word(db, "discuss", "talk about something")
    assert await vocab_repo.delete_word(db, doc["_id"]) is True
    assert await vocab_repo.count_vocabulary(db) == 0
