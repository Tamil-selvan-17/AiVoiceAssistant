"""
Shared FastAPI dependencies.

No authentication dependency exists here by design -- this is a single-user
application (see project spec, section 6).
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings, get_settings
from app.db.mongodb import get_database

__all__ = ["get_database", "get_settings", "Settings", "DatabaseDep"]

# Convenience alias for route signatures: db: DatabaseDep
DatabaseDep = AsyncIOMotorDatabase
