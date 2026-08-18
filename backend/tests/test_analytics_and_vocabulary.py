"""Tests for /api/analytics/* and /api/vocabulary/*, plus the /analyze
idempotency guard added alongside them."""
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.db.collections import CONVERSATION_ANALYSIS
from app.db.mongodb import get_database
from app.main import app
from app.services.storage import conversation_repository as repo
from app.services.storage import vocabulary_repository as vocab_repo


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


async def _seed_analyzed_conversation(db, topic="Job Interview"):
    conversation = await repo.create_conversation(
        db, {"topic": topic, "ai_provider": "gemini", "difficulty": "intermediate",
             "mother_language": "Tamil", "target_language": "English", "ai_model": ""}
    )
    await db[CONVERSATION_ANALYSIS].insert_one(
        {
            "_id": f"a-{conversation['_id']}",
            "conversation_id": conversation["_id"],
            "grammar_score": 80,
            "fluency_score": 75,
            "confidence_score": 70,
            "vocabulary_score": 65,
            "pronunciation_score": None,
            "corrections": [{"original": "x", "corrected": "y", "explanation": "Use past tense here."}],
            "new_words": [{"word": "discuss", "meaning": "talk about"}],
            "filler_word_count": 2,
        }
    )
    return conversation


# --- /api/analytics/dashboard ---


@pytest.mark.asyncio
async def test_dashboard_empty_state(client):
    response = await client.get("/api/analytics/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["total_conversations"] == 0
    assert body["recent_conversations"] == []
    assert body["frequent_mistakes"] == []


@pytest.mark.asyncio
async def test_dashboard_reflects_analyzed_conversation(client, mock_db):
    conversation = await _seed_analyzed_conversation(mock_db)
    await client.post(f"/api/conversations/{conversation['_id']}/analyze")

    response = await client.get("/api/analytics/dashboard")
    body = response.json()

    assert body["total_conversations"] == 1
    assert body["vocabulary_learned_count"] == 1
    assert len(body["recent_conversations"]) == 1
    assert body["recent_conversations"][0]["topic"] == "Job Interview"
    assert body["recent_conversations"][0]["overall_score"] is not None
    assert any(m["category"] == "Past tense" for m in body["frequent_mistakes"])


# --- /api/analytics/progress ---


@pytest.mark.asyncio
async def test_progress_only_includes_analyzed_conversations(client, mock_db):
    analyzed = await _seed_analyzed_conversation(mock_db)
    await repo.create_conversation(mock_db, {"topic": "Casual Conversation", "ai_provider": "gemini"})  # never analyzed

    await client.post(f"/api/conversations/{analyzed['_id']}/analyze")

    response = await client.get("/api/analytics/progress")
    points = response.json()["points"]
    assert len(points) == 1
    assert points[0]["conversation_id"] == analyzed["_id"]


# --- /analyze idempotency ---


@pytest.mark.asyncio
async def test_analyze_twice_does_not_double_count_progress(client, mock_db):
    conversation = await _seed_analyzed_conversation(mock_db)

    await client.post(f"/api/conversations/{conversation['_id']}/analyze")
    await client.post(f"/api/conversations/{conversation['_id']}/analyze")  # called again

    dashboard = (await client.get("/api/analytics/dashboard")).json()
    assert dashboard["total_conversations"] == 1  # not 2


# --- /api/vocabulary ---


@pytest.mark.asyncio
async def test_list_vocabulary(client, mock_db):
    await vocab_repo.upsert_word(mock_db, "discuss", "talk about something")
    response = await client.get("/api/vocabulary")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["word"] == "discuss"
    assert "id" in body[0]


@pytest.mark.asyncio
async def test_delete_vocabulary_word(client, mock_db):
    doc = await vocab_repo.upsert_word(mock_db, "discuss", "talk about something")
    response = await client.delete(f"/api/vocabulary/{doc['_id']}")
    assert response.status_code == 200

    remaining = await client.get("/api/vocabulary")
    assert remaining.json() == []


@pytest.mark.asyncio
async def test_delete_missing_vocabulary_word_returns_404(client):
    response = await client.delete("/api/vocabulary/does-not-exist")
    assert response.status_code == 404
