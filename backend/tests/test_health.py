"""
Tests for the health and readiness endpoints. These do not hit a real
MongoDB or AI provider -- they only verify the HTTP contract described in
the project spec (section 51).
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_endpoint_returns_healthy():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "ai-voice-assistant"
    assert "version" in body


@pytest.mark.asyncio
async def test_readiness_endpoint_reports_checks():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health/ready")

    # Readiness can legitimately be "not_ready" in a test environment with no
    # live MongoDB -- what matters is the endpoint responds with the correct
    # shape rather than crashing.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ready", "not_ready"}
    assert set(body["checks"].keys()) == {
        "mongodb",
        "ai_provider_configured",
        "gemini_configured",
        "nvidia_configured",
    }


@pytest.mark.asyncio
async def test_error_responses_use_standard_shape():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert "message" in body
    assert "error_code" in body
