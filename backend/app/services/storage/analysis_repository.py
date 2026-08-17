"""Read access to the `conversation_analysis` collection (written by
conversation_manager._analyze_turn during live turns)."""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import CONVERSATION_ANALYSIS


async def get_analysis_entries(db: AsyncIOMotorDatabase, conversation_id: str) -> list[dict]:
    cursor = db[CONVERSATION_ANALYSIS].find({"conversation_id": conversation_id}).sort("created_at", 1)
    return [doc async for doc in cursor]
