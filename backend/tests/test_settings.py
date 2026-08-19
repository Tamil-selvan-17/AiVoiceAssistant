"""
Tests for /api/settings and /api/ai/*. Mongo access is faked with
mongomock-motor (an in-memory drop-in for AsyncIOMotorClient) via a
dependency override, so these tests need neither a real MongoDB nor real
AI provider credentials.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import get_settings
from app.db.mongodb import get_database
from app.main import app


@pytest.fixture
def mock_db():
    client = AsyncMongoMockClient()
    return client["ai_voice_assistant_test"]


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


# ---------------------------------------------------------------------------
# /api/settings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_settings_returns_defaults_on_first_call(client):
    response = await client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["mother_language"] == "Tamil"
    assert body["target_language"] == "English"
    assert body["difficulty"] == "beginner"
    assert body["ai_provider"] == "gemini"
    assert body["save_audio"] is False  # must default to off, per spec §49


@pytest.mark.asyncio
async def test_put_settings_applies_partial_update(client):
    response = await client.put("/api/settings", json={"ai_provider": "nvidia", "difficulty": "advanced"})
    assert response.status_code == 200
    body = response.json()
    assert body["ai_provider"] == "nvidia"
    assert body["difficulty"] == "advanced"
    # Untouched fields should be preserved, not reset.
    assert body["mother_language"] == "Tamil"

    # A follow-up GET should reflect the persisted change.
    response = await client.get("/api/settings")
    assert response.json()["ai_provider"] == "nvidia"


@pytest.mark.asyncio
async def test_put_settings_rejects_invalid_provider(client):
    response = await client.put("/api/settings", json={"ai_provider": "chatgpt"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_put_settings_rejects_out_of_range_speaking_speed(client):
    response = await client.put("/api/settings", json={"speaking_speed": 5.0})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# /api/ai
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_providers_reports_configuration_state(client):
    def fake_settings():
        s = get_settings()
        return s.model_copy(update={"gemini_api_key": "abc", "nvidia_api_key": ""})

    app.dependency_overrides[get_settings] = fake_settings
    try:
        response = await client.get("/api/ai/providers")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    providers = {p["id"]: p["configured"] for p in response.json()["providers"]}
    assert providers == {"gemini": True, "nvidia": False}


@pytest.mark.asyncio
async def test_list_models_without_key_falls_back_to_configured_model(client):
    def fake_settings():
        s = get_settings()
        return s.model_copy(update={"gemini_api_key": "", "gemini_model": "gemini-2.5-flash"})

    app.dependency_overrides[get_settings] = fake_settings
    try:
        response = await client.get("/api/ai/models", params={"provider": "gemini"})
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "gemini"
    assert body["models"] == ["gemini-2.5-flash"]


@pytest.mark.asyncio
async def test_list_models_rejects_unknown_provider(client):
    response = await client.get("/api/ai/models", params={"provider": "chatgpt"})
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error_code"] == "UNKNOWN_AI_PROVIDER"
