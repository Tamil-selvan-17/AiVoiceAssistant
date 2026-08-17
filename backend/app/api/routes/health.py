"""
Health and readiness endpoints.

/api/health        -> liveness: is the process up at all?
/api/health/ready   -> readiness: are downstream dependencies (MongoDB,
                       AI provider config) usable right now?
"""
from fastapi import APIRouter

from app.core.config import get_settings
from app.db.mongodb import ping_mongo

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health():
    settings = get_settings()
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready")
async def readiness():
    settings = get_settings()

    mongo_ok = await ping_mongo()
    gemini_configured = bool(settings.gemini_api_key)
    nvidia_configured = bool(settings.nvidia_api_key)
    ai_provider_ready = gemini_configured or nvidia_configured

    checks = {
        "mongodb": "ok" if mongo_ok else "unavailable",
        "ai_provider_configured": ai_provider_ready,
        "gemini_configured": gemini_configured,
        "nvidia_configured": nvidia_configured,
    }

    overall_ok = mongo_ok and ai_provider_ready

    return {
        "status": "ready" if overall_ok else "not_ready",
        "checks": checks,
    }
