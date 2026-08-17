"""
Tests for POST /api/conversations/{id}/analyze. Sets up fixture data
directly via the repositories (bypassing the full WS+AI turn flow, which is
already covered in test_conversation_websocket.py) so this test focuses
purely on the aggregation/summary endpoint itself.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.db.collections import CONVERSATION_ANALYSIS
from app.db.mongodb import get_database
from app.main import app
from app.services.storage import conversation_repository as repo
from app.services.storage import learning_progress_repository as progress_repo


@pytest.fixture
def mock_db():
    return AsyncMongoMockClient()["test_db"]


@pytest.fixture(autouse=True)
def override_database(mock_db):
    app.dependency_overrides[get_database] = lambda: mock_db
    yield
    app.dependency_overrides.pop(get_database, None)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_analyzed_conversation(db):
    conversation = await repo.create_conversation(
        db, {"topic": "Job Interview", "ai_provider": "gemini", "difficulty": "intermediate",
             "mother_language": "Tamil", "target_language": "English", "ai_model": ""}
    )
    await repo.add_message(db, conversation["_id"], "assistant", "Tell me about yourself.", "en")
    await repo.add_message(db, conversation["_id"], "user", "I am a software developer.", "en")

    await db[CONVERSATION_ANALYSIS].insert_many(
        [
            {
                "_id": "a1",
                "conversation_id": conversation["_id"],
                "grammar_score": 85,
                "fluency_score": 80,
                "confidence_score": 75,
                "vocabulary_score": 70,
                "pronunciation_score": None,
                "corrections": [],
                "new_words": [{"word": "developer", "meaning": "someone who builds software"}],
                "filler_word_count": 1,
            },
            {
                "_id": "a2",
                "conversation_id": conversation["_id"],
                "grammar_score": 90,
                "fluency_score": 85,
                "confidence_score": 80,
                "vocabulary_score": 75,
                "pronunciation_score": None,
                "corrections": [],
                "new_words": [],
                "filler_word_count": 0,
            },
        ]
    )
    return conversation


@pytest.mark.asyncio
async def test_analyze_returns_averaged_scores(client, mock_db):
    conversation = await _seed_analyzed_conversation(mock_db)

    response = await client.post(f"/api/conversations/{conversation['_id']}/analyze")
    assert response.status_code == 200
    body = response.json()

    assert body["grammar_score"] == 88  # avg(85, 90) rounded
    assert body["fluency_score"] == 82  # avg(80, 85) = 82.5 -> banker's rounding -> 82
    assert body["filler_word_count"] == 1
    assert body["new_words_learned"] == 1
    assert body["pronunciation_score"] is None
    assert "acoustic" in body["pronunciation_note"].lower() or "phoneme" in body["pronunciation_note"].lower()
    assert body["what_went_well"]
    assert body["improve_next_time"]


@pytest.mark.asyncio
async def test_analyze_ends_an_active_conversation(client, mock_db):
    conversation = await _seed_analyzed_conversation(mock_db)
    assert conversation["status"] == "active"

    await client.post(f"/api/conversations/{conversation['_id']}/analyze")

    updated = await repo.get_conversation(mock_db, conversation["_id"])
    assert updated["status"] == "completed"
    assert updated["ended_at"] is not None


@pytest.mark.asyncio
async def test_analyze_updates_learning_progress(client, mock_db):
    conversation = await _seed_analyzed_conversation(mock_db)

    before = await progress_repo.get_progress(mock_db)
    assert before["total_conversations"] == 0

    await client.post(f"/api/conversations/{conversation['_id']}/analyze")

    after = await progress_repo.get_progress(mock_db)
    assert after["total_conversations"] == 1
    assert after["vocabulary_learned_count"] == 1
    assert after["current_streak_days"] == 1


@pytest.mark.asyncio
async def test_analyze_missing_conversation_returns_404(client):
    response = await client.post("/api/conversations/does-not-exist/analyze")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_analyze_with_no_turns_does_not_crash(client, mock_db):
    conversation = await repo.create_conversation(mock_db, {"topic": "Casual Conversation", "ai_provider": "gemini"})
    response = await client.post(f"/api/conversations/{conversation['_id']}/analyze")
    assert response.status_code == 200
    assert response.json()["overall_score"] == 0
