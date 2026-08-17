"""
Application entrypoint.

Run locally with:

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

Run in production (e.g. on Render) with:

    uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import ai as ai_routes
from app.api.routes import conversation_ws as conversation_ws_routes
from app.api.routes import conversations as conversations_routes
from app.api.routes import health as health_routes
from app.api.routes import settings as settings_routes
from app.api.routes import voice as voice_routes
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.core.middleware import register_middleware
from app.db.collections import ensure_indexes
from app.db.mongodb import close_mongo_connection, connect_to_mongo, mongodb

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("app_starting", extra={"env": settings.app_env})

    await connect_to_mongo()
    if mongodb.database is not None:
        try:
            await ensure_indexes(mongodb.database)
        except Exception:
            # Index creation failing shouldn't crash startup -- readiness
            # checks will still reflect a degraded MongoDB state.
            logger.error("mongodb_index_setup_failed")

    yield

    logger.info("app_stopping")
    await close_mongo_connection()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AI Voice Communication Assistant",
        version=settings.app_version,
        description=(
            "Backend for a single-user AI voice English-speaking coach. "
            "No authentication -- see docs/DEVELOPER_GUIDE.md."
        ),
        docs_url="/docs" if settings.enable_api_docs else None,
        redoc_url="/redoc" if settings.enable_api_docs else None,
        lifespan=lifespan,
    )

    register_middleware(app)
    register_exception_handlers(app)

    app.include_router(health_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(ai_routes.router)
    app.include_router(voice_routes.router)
    app.include_router(conversations_routes.router)
    app.include_router(conversation_ws_routes.router)

    # Frontend is a static, framework-free site that normally sits alongside
    # `backend/` in the repo. Mounted last so it never shadows API routes,
    # and only if present -- this keeps API-only deployments (e.g. a bare
    # backend Docker image) from failing to start.
    frontend_dir = os.getenv("FRONTEND_DIR", "../frontend")
    if os.path.isdir(frontend_dir):
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
    else:
        logger.info("frontend_dir_not_found", extra={"frontend_dir": frontend_dir})

    return app


app = create_app()
