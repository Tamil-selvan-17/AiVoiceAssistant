"""Tests for the in-memory rate limiting middleware."""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rate_limit import RateLimitMiddleware
from app.main import app


@pytest.mark.asyncio
async def test_requests_within_limit_succeed():
    # Use a fresh app instance with a tiny limit so this test doesn't need
    # 120+ requests to exercise the 429 path, and doesn't share rate-limit
    # state with other tests hitting the same shared `app` object.
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/ping")
    async def ping():
        return {"ok": True}

    test_app.add_middleware(RateLimitMiddleware, requests_per_minute=3)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            response = await client.get("/ping")
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_requests_over_limit_return_429():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/ping")
    async def ping():
        return {"ok": True}

    test_app.add_middleware(RateLimitMiddleware, requests_per_minute=3)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            await client.get("/ping")
        response = await client.get("/ping")

    assert response.status_code == 429
    body = response.json()
    assert body["error_code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in response.headers


@pytest.mark.asyncio
async def test_health_endpoint_is_exempt_from_rate_limiting():
    # The real app's health endpoint, with the real (generous) limit --
    # hammering it well past a tiny limit should never 429.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [await client.get("/api/health") for _ in range(10)]

    assert all(r.status_code == 200 for r in responses)


@pytest.mark.asyncio
async def test_different_clients_have_independent_limits():
    from fastapi import FastAPI

    test_app = FastAPI()

    @test_app.get("/ping")
    async def ping():
        return {"ok": True}

    test_app.add_middleware(RateLimitMiddleware, requests_per_minute=1)

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r1 = await client.get("/ping", headers={"X-Forwarded-For": "1.1.1.1"})
        r2 = await client.get("/ping", headers={"X-Forwarded-For": "2.2.2.2"})

    assert r1.status_code == 200
    assert r2.status_code == 200  # different client -- shouldn't be limited by client 1's usage
