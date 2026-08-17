"""
MongoDB collection name constants and index definitions.

Keeping collection names in one place avoids typos scattered across
repositories and makes it obvious, at a glance, that no `users` collection
exists in this application (there is no authentication -- see project spec).
"""
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.logging import get_logger

logger = get_logger(__name__)

CONVERSATIONS = "conversations"
CONVERSATION_MESSAGES = "conversation_messages"
CONVERSATION_ANALYSIS = "conversation_analysis"
VOCABULARY = "vocabulary"
LEARNING_PROGRESS = "learning_progress"
APP_SETTINGS = "app_settings"

ALL_COLLECTIONS = [
    CONVERSATIONS,
    CONVERSATION_MESSAGES,
    CONVERSATION_ANALYSIS,
    VOCABULARY,
    LEARNING_PROGRESS,
    APP_SETTINGS,
]


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create indexes needed for common query patterns. Safe to call on every
    startup -- creating an index that already exists is a no-op in MongoDB.
    """
    await db[CONVERSATIONS].create_index("status")
    await db[CONVERSATIONS].create_index("started_at")

    await db[CONVERSATION_MESSAGES].create_index("conversation_id")
    await db[CONVERSATION_MESSAGES].create_index(
        [("conversation_id", 1), ("timestamp", 1)]
    )

    await db[CONVERSATION_ANALYSIS].create_index("conversation_id")
    await db[CONVERSATION_ANALYSIS].create_index("message_id")

    await db[VOCABULARY].create_index("word", unique=True)
    await db[VOCABULARY].create_index("difficulty")

    await db[LEARNING_PROGRESS].create_index("updated_at")

    logger.info("mongodb_indexes_ensured")
