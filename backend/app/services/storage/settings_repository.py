"""
Repository for the single app_settings document. There is exactly one
document, with a fixed _id, since this app has no user accounts.
"""
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import APP_SETTINGS
from app.schemas.settings import AppSettingsSchema

DEFAULT_SETTINGS_ID = "default"


async def get_settings_doc(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    """Return the settings document, creating it with defaults if missing."""
    doc = await db[APP_SETTINGS].find_one({"_id": DEFAULT_SETTINGS_ID})
    if doc is not None:
        return doc

    defaults = AppSettingsSchema().model_dump()
    defaults["_id"] = DEFAULT_SETTINGS_ID
    await db[APP_SETTINGS].insert_one(defaults)
    return defaults


async def update_settings_doc(
    db: AsyncIOMotorDatabase, updates: dict[str, Any]
) -> dict[str, Any]:
    """Apply a partial update (None values are ignored) and return the result."""
    clean_updates = {k: v for k, v in updates.items() if v is not None}

    # Ensure the document exists first so $set with upsert can't create a
    # document that's missing fields the schema expects.
    await get_settings_doc(db)

    if clean_updates:
        await db[APP_SETTINGS].update_one(
            {"_id": DEFAULT_SETTINGS_ID}, {"$set": clean_updates}
        )
    return await get_settings_doc(db)
