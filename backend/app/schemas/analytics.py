"""Schemas for /api/analytics/* (project spec §39-40, §43)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ConversationHistoryItem(BaseModel):
    id: str
    topic: str
    started_at: datetime
    duration_seconds: Optional[int] = None
    status: str
    overall_score: Optional[int] = None
    grammar_score: Optional[int] = None
    fluency_score: Optional[int] = None
    confidence_score: Optional[int] = None
    vocabulary_score: Optional[int] = None


class MistakePattern(BaseModel):
    category: str
    count: int
    tip: str


class DashboardResponse(BaseModel):
    total_conversations: int
    total_speaking_seconds: int
    avg_fluency: float
    avg_confidence: float
    avg_grammar: float
    avg_vocabulary: float
    vocabulary_learned_count: int
    current_streak_days: int
    recent_conversations: list[ConversationHistoryItem]
    frequent_mistakes: list[MistakePattern]


class ProgressPoint(BaseModel):
    conversation_id: str
    date: datetime
    overall_score: int
    fluency_score: int
    confidence_score: int
    grammar_score: int
    vocabulary_score: int


class ProgressResponse(BaseModel):
    points: list[ProgressPoint]
