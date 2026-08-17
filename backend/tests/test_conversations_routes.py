"""
Minimal tests for /api/conversations. Mongo is faked with mongomock-motor
via dependency override, same pattern as test_settings.py.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.db.mongodb import get_database
from app.main import app


@pytest.fixture(autouse=True)
def override_database():
    client = AsyncMongoMockClient()["test_db"]
    app.dependency_overrides[get_database] = lambda: client
    yield
    app.dependency_overrides.pop(get_database, None)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_create_conversation_falls_back_to_app_settings(client):
    response = await client.post("/api/conversations", json={"topic": "Job Interview"})
    assert response.status_code == 200
    body = response.json()
    assert body["topic"] == "Job Interview"
    assert body["mother_language"] == "Tamil"  # default from app_settings
    assert body["status"] == "active"


@pytest.mark.asyncio
async def test_create_conversation_surprise_me_picks_a_real_topic(client):
    from app.schemas.conversation import CONVERSATION_TOPICS

    response = await client.post("/api/conversations", json={"topic": "Surprise Me"})
    assert response.json()["topic"] in CONVERSATION_TOPICS


@pytest.mark.asyncio
async def test_get_conversation_by_id(client):
    created = (await client.post("/api/conversations", json={})).json()
    response = await client.get(f"/api/conversations/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_missing_conversation_returns_404(client):
    response = await client.get("/api/conversations/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error_code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_list_conversations_includes_created_ones(client):
    await client.post("/api/conversations", json={})
    response = await client.get("/api/conversations")
    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_delete_conversation(client):
    created = (await client.post("/api/conversations", json={})).json()
    response = await client.delete(f"/api/conversations/{created['id']}")
    assert response.status_code == 200

    follow_up = await client.get(f"/api/conversations/{created['id']}")
    assert follow_up.status_code == 404
