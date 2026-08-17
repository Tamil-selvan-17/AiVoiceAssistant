"""
Async MongoDB connection management using Motor.

A single AsyncIOMotorClient is created at application startup and closed at
shutdown (see app/main.py's lifespan handler). Route/service code should
obtain the database via `get_database()` (as a FastAPI dependency) rather
than importing a client directly, which keeps the app testable.
"""
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo.errors import PyMongoError

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class MongoDB:
    """Thin wrapper holding the Motor client/database for the app lifetime."""

    client: Optional[AsyncIOMotorClient] = None
    database: Optional[AsyncIOMotorDatabase] = None


mongodb = MongoDB()


async def connect_to_mongo() -> None:
    """Create the Motor client and verify connectivity. Call on startup."""
    settings = get_settings()
    logger.info("mongodb_connecting", extra={"database": settings.mongodb_database})

    mongodb.client = AsyncIOMotorClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=5000,
    )
    mongodb.database = mongodb.client[settings.mongodb_database]

    try:
        await mongodb.client.admin.command("ping")
        logger.info("mongodb_connected", extra={"database": settings.mongodb_database})
    except PyMongoError:
        # Don't crash the whole app if Mongo is briefly unavailable at boot --
        # readiness checks (/api/health/ready) will surface this to callers.
        logger.error("mongodb_connection_failed")


async def close_mongo_connection() -> None:
    """Close the Motor client. Call on shutdown."""
    if mongodb.client is not None:
        mongodb.client.close()
        logger.info("mongodb_connection_closed")


async def ping_mongo() -> bool:
    """Used by readiness checks. Returns True if Mongo is reachable."""
    if mongodb.client is None:
        return False
    try:
        await mongodb.client.admin.command("ping")
        return True
    except PyMongoError:
        return False


def get_database() -> AsyncIOMotorDatabase:
    """
    FastAPI dependency: returns the shared database handle.

    Raises RuntimeError if called before connect_to_mongo() has run, which
    would indicate a startup ordering bug rather than a normal runtime error.
    """
    if mongodb.database is None:
        raise RuntimeError("MongoDB has not been initialized yet.")
    return mongodb.database
