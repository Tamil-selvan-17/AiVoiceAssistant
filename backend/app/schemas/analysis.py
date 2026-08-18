"""Schemas for learning analysis (project spec §28-31, §34-38)."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CorrectionSchema(BaseModel):
    original: str
    corrected: str
    explanation: str


class VocabularyWordSchema(BaseModel):
    word: str
    meaning: str
    translation: str = ""
    example: str = ""
    difficulty: str = "beginner"


class VocabularyEntryResponse(BaseModel):
    """A stored vocabulary collection document (project spec §30)."""

    id: str
    word: str
    meaning: str
    translation: str = ""
    example: str = ""
    pronunciation: str = ""
    difficulty: str = "beginner"
    first_seen: datetime
    review_count: int


class ConversationSummaryResponse(BaseModel):
    """The end-of-conversation summary (project spec §34, §38)."""

    conversation_id: str
    topic: str
    duration_seconds: int
    message_count: int

    overall_score: int
    fluency_score: int
    confidence_score: int
    grammar_score: int
    vocabulary_score: int
    pronunciation_score: Optional[int] = None
    pronunciation_note: str

    filler_word_count: int
    new_words_learned: int

    what_went_well: list[str]
    improve_next_time: list[str]
