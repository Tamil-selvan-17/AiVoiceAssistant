"""
Simple in-memory per-IP rate limiting (sliding window). Deliberately not
Redis-backed -- this is a single-instance deployment (project spec §63:
don't add Redis/queues/microservices unless actually required), so an
in-process counter is sufficient and avoids a whole extra infrastructure
dependency for a single-user, hobby-scale app.

Health checks and docs are exempt so Render's own health probe (and a
developer poking at /docs) never gets a spurious 429.
"""
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger

logger = get_logger(__name__)

_EXEMPT_PREFIXES = ("/api/health", "/docs", "/redoc", "/openapi.json")

# If the number of distinct client keys we're tracking grows past this,
# opportunistically drop empty entries -- keeps memory bounded for a
# long-running process without needing a background task/scheduler.
_MAX_TRACKED_CLIENTS = 10_000


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 120):
        super().__init__(app)
        self.limit = requests_per_minute
        self.window_seconds = 60.0
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    @staticmethod
    def _client_key(request: Request) -> str:
        # Render (and most PaaS) sit behind a proxy -- prefer the forwarded
        # client IP when present, falling back to the direct connection.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _prune_if_large(self) -> None:
        if len(self._hits) <= _MAX_TRACKED_CLIENTS:
            return
        empty_keys = [k for k, v in self._hits.items() if not v]
        for k in empty_keys:
            del self._hits[k]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if any(request.url.path.startswith(p) for p in _EXEMPT_PREFIXES):
            return await call_next(request)

        key = self._client_key(request)
        now = time.monotonic()
        hits = self._hits[key]

        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()

        if len(hits) >= self.limit:
            logger.warning(
                "rate_limit_exceeded", extra={"client": key, "path": request.url.path}
            )
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "message": "Too many requests. Please slow down and try again shortly.",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                },
                headers={"Retry-After": "60"},
            )

        hits.append(now)
        self._prune_if_large()
        return await call_next(request)
