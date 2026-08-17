"""
Repository for the `vocabulary` collection (project spec §30). A word seen
again in a later conversation increments `review_count` on the existing
document rather than creating a duplicate.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import VOCABULARY


def _normalize(word: str) -> str:
    return word.strip().lower()


async def upsert_word(
    db: AsyncIOMotorDatabase,
    word: str,
    meaning: str,
    translation: str = "",
    example: str = "",
    difficulty: str = "beginner",
) -> dict[str, Any]:
    key = _normalize(word)
    if not key:
        raise ValueError("word must not be empty")

    existing = await db[VOCABULARY].find_one({"word": key})
    if existing:
        await db[VOCABULARY].update_one({"_id": existing["_id"]}, {"$inc": {"review_count": 1}})
        return await db[VOCABULARY].find_one({"_id": existing["_id"]})

    doc = {
        "_id": str(uuid.uuid4()),
        "word": key,
        "meaning": meaning,
        "translation": translation,
        "example": example,
        "pronunciation": "",
        "difficulty": difficulty,
        "first_seen": datetime.now(timezone.utc),
        "review_count": 1,
    }
    await db[VOCABULARY].insert_one(doc)
    return doc


async def list_vocabulary(db: AsyncIOMotorDatabase, limit: int = 200) -> list[dict]:
    cursor = db[VOCABULARY].find().sort("first_seen", -1).limit(limit)
    return [doc async for doc in cursor]


async def count_vocabulary(db: AsyncIOMotorDatabase) -> int:
    return await db[VOCABULARY].count_documents({})


async def delete_word(db: AsyncIOMotorDatabase, word_id: str) -> bool:
    result = await db[VOCABULARY].delete_one({"_id": word_id})
    return result.deleted_count > 0
