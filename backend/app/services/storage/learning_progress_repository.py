"""
Repository for the single `learning_progress` document (project spec §39).
This is deliberately minimal for Phase 5: it persists the rolling aggregates
a Phase 6 dashboard will read (total conversations, average scores, streak),
updated once per completed conversation. Building the dashboard views/charts
themselves is Phase 6's job, not this file's.
"""
from datetime import datetime, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.collections import LEARNING_PROGRESS

DEFAULT_ID = "default"

_DEFAULTS: dict[str, Any] = {
    "_id": DEFAULT_ID,
    "total_conversations": 0,
    "total_speaking_seconds": 0,
    "avg_fluency": 0.0,
    "avg_confidence": 0.0,
    "avg_grammar": 0.0,
    "avg_vocabulary": 0.0,
    "vocabulary_learned_count": 0,
    "current_streak_days": 0,
    "last_conversation_date": None,  # ISO date string (UTC), not a datetime
    "updated_at": None,
}


async def get_progress(db: AsyncIOMotorDatabase) -> dict[str, Any]:
    doc = await db[LEARNING_PROGRESS].find_one({"_id": DEFAULT_ID})
    return doc if doc is not None else dict(_DEFAULTS)


def compute_next_streak(last_date_str: str | None, today_str: str, current_streak: int) -> int:
    """
    Returns the streak count *after* today's conversation.
    - No prior conversation: streak starts at 1.
    - Already logged a conversation today: streak unchanged.
    - Last conversation was yesterday: streak continues (+1).
    - Any bigger gap: streak resets to 1.
    """
    if last_date_str is None:
        return 1
    if last_date_str == today_str:
        return current_streak or 1
    last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
    today = datetime.strptime(today_str, "%Y-%m-%d").date()
    gap_days = (today - last_date).days
    if gap_days == 1:
        return (current_streak or 0) + 1
    return 1


def _running_average(previous_avg: float, previous_count: int, new_value: float) -> float:
    if previous_count <= 0:
        return new_value
    return ((previous_avg * previous_count) + new_value) / (previous_count + 1)


async def record_conversation_completion(
    db: AsyncIOMotorDatabase,
    duration_seconds: int,
    fluency_score: int,
    confidence_score: int,
    grammar_score: int,
    vocabulary_score: int,
    new_words_learned: int,
) -> dict[str, Any]:
    """Called once when a conversation ends, to fold its results into the
    rolling aggregate. Returns the updated document."""
    current = await get_progress(db)
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")

    prior_count = current.get("total_conversations", 0)
    updated = {
        "_id": DEFAULT_ID,
        "total_conversations": prior_count + 1,
        "total_speaking_seconds": current.get("total_speaking_seconds", 0) + max(0, duration_seconds),
        "avg_fluency": round(_running_average(current.get("avg_fluency", 0.0), prior_count, fluency_score), 1),
        "avg_confidence": round(
            _running_average(current.get("avg_confidence", 0.0), prior_count, confidence_score), 1
        ),
        "avg_grammar": round(_running_average(current.get("avg_grammar", 0.0), prior_count, grammar_score), 1),
        "avg_vocabulary": round(
            _running_average(current.get("avg_vocabulary", 0.0), prior_count, vocabulary_score), 1
        ),
        "vocabulary_learned_count": current.get("vocabulary_learned_count", 0) + max(0, new_words_learned),
        "current_streak_days": compute_next_streak(
            current.get("last_conversation_date"), today_str, current.get("current_streak_days", 0)
        ),
        "last_conversation_date": today_str,
        "updated_at": now,
    }

    await db[LEARNING_PROGRESS].update_one({"_id": DEFAULT_ID}, {"$set": updated}, upsert=True)
    return updated
