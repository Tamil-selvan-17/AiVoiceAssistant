"""
Repository for the `conversations` and `conversation_messages` collections.
Each conversation gets its own UUID (project spec §8) since there's no
authentication to scope documents by user.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import CONVERSATION_ANALYSIS, CONVERSATION_MESSAGES, CONVERSATIONS


def new_id() -> str:
    return str(uuid.uuid4())


def _as_aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def create_conversation(db: AsyncIOMotorDatabase, fields: dict[str, Any]) -> dict[str, Any]:
    doc = dict(fields)
    doc["_id"] = doc.get("_id") or new_id()
    doc["started_at"] = datetime.now(timezone.utc)
    doc["ended_at"] = None
    doc["duration_seconds"] = None
    doc["status"] = "active"
    await db[CONVERSATIONS].insert_one(doc)
    return doc


async def get_conversation(db: AsyncIOMotorDatabase, conversation_id: str) -> Optional[dict]:
    return await db[CONVERSATIONS].find_one({"_id": conversation_id})


async def list_conversations(db: AsyncIOMotorDatabase, limit: int = 50) -> list[dict]:
    cursor = db[CONVERSATIONS].find().sort("started_at", -1).limit(limit)
    return [doc async for doc in cursor]


async def end_conversation(db: AsyncIOMotorDatabase, conversation_id: str) -> Optional[dict]:
    conversation = await get_conversation(db, conversation_id)
    if conversation is None:
        return None

    ended_at = datetime.now(timezone.utc)
    started_at = _as_aware_utc(conversation["started_at"])
    duration_seconds = int((ended_at - started_at).total_seconds())

    await db[CONVERSATIONS].update_one(
        {"_id": conversation_id},
        {
            "$set": {
                "ended_at": ended_at,
                "duration_seconds": duration_seconds,
                "status": "completed",
            }
        },
    )
    return await get_conversation(db, conversation_id)


async def delete_conversation(db: AsyncIOMotorDatabase, conversation_id: str) -> bool:
    result = await db[CONVERSATIONS].delete_one({"_id": conversation_id})
    await db[CONVERSATION_MESSAGES].delete_many({"conversation_id": conversation_id})
    await db[CONVERSATION_ANALYSIS].delete_many({"conversation_id": conversation_id})
    return result.deleted_count > 0


async def add_message(
    db: AsyncIOMotorDatabase,
    conversation_id: str,
    speaker: str,
    text: str,
    language: str = "",
) -> dict[str, Any]:
    doc = {
        "_id": new_id(),
        "conversation_id": conversation_id,
        "speaker": speaker,
        "text": text,
        "language": language,
        "timestamp": datetime.now(timezone.utc),
    }
    await db[CONVERSATION_MESSAGES].insert_one(doc)
    return doc


async def get_messages(db: AsyncIOMotorDatabase, conversation_id: str) -> list[dict]:
    cursor = (
        db[CONVERSATION_MESSAGES].find({"conversation_id": conversation_id}).sort("timestamp", 1)
    )
    return [doc async for doc in cursor]


async def count_assistant_messages_today(db: AsyncIOMotorDatabase) -> int:
    """
    Used for MAX_DAILY_AI_REQUESTS (project spec §47): counts assistant
    replies (one per AI request) created since UTC midnight, across all
    conversations -- there's no per-user scoping since there's no auth.
    """
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return await db[CONVERSATION_MESSAGES].count_documents(
        {"speaker": "assistant", "timestamp": {"$gte": start_of_day}}
    )
