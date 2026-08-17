"""Schemas for /api/conversations/* and the preset conversation topics
(project spec §25, §33)."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Difficulty = Literal["beginner", "intermediate", "advanced"]
Provider = Literal["gemini", "nvidia"]

CONVERSATION_TOPICS = [
    "Casual Conversation",
    "Job Interview",
    "Office Conversation",
    "Meeting Practice",
    "Presentation Practice",
    "Customer Conversation",
    "Travel Conversation",
    "Daily English",
    "Debate",
    "Storytelling",
    "Vocabulary Practice",
]

SURPRISE_ME = "Surprise Me"


class ConversationCreate(BaseModel):
    """All fields optional -- unset values fall back to app_settings."""

    topic: Optional[str] = Field(default=None, description="A preset topic, 'Surprise Me', or omitted")
    difficulty: Optional[Difficulty] = None
    mother_language: Optional[str] = None
    target_language: Optional[str] = None
    ai_provider: Optional[Provider] = None
    ai_model: Optional[str] = None


class ConversationResponse(BaseModel):
    id: str
    topic: str
    difficulty: str
    mother_language: str
    target_language: str
    ai_provider: str
    ai_model: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    status: str


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    speaker: str
    text: str
    language: str
    timestamp: datetime
