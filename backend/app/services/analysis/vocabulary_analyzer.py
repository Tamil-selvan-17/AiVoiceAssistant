"""
Vocabulary detection and persistence (project spec §30). Like
grammar_analyzer, this consumes the shared ai_turn_analysis result rather
than making its own AI call.
"""
from dataclasses import dataclass, field
from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.services.analysis.ai_turn_analysis import RawTurnAnalysis
from app.services.storage import vocabulary_repository as vocab_repo

_VALID_DIFFICULTIES = {"beginner", "intermediate", "advanced"}


@dataclass
class VocabWord:
    word: str
    meaning: str
    translation: str = ""
    example: str = ""
    difficulty: str = "beginner"


@dataclass
class VocabularyResult:
    words: list[VocabWord] = field(default_factory=list)


def _valid_word(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("word"), str)
        and item.get("word", "").strip()
        and isinstance(item.get("meaning"), str)
        and item.get("meaning", "").strip()
    )


def _clean_difficulty(value: Any) -> str:
    value = str(value).strip().lower() if value else ""
    return value if value in _VALID_DIFFICULTIES else "beginner"


def analyze_vocabulary(raw: RawTurnAnalysis) -> VocabularyResult:
    words = [
        VocabWord(
            word=item["word"].strip(),
            meaning=item["meaning"].strip(),
            translation=str(item.get("translation", "")).strip(),
            example=str(item.get("example", "")).strip(),
            difficulty=_clean_difficulty(item.get("difficulty")),
        )
        for item in raw.new_words
        if _valid_word(item)
    ]
    return VocabularyResult(words=words)


async def persist_vocabulary(db: AsyncIOMotorDatabase, result: VocabularyResult) -> None:
    """Upserts each detected word -- repeats increment review_count rather
    than creating duplicates (see vocabulary_repository)."""
    for word in result.words:
        await vocab_repo.upsert_word(
            db,
            word=word.word,
            meaning=word.meaning,
            translation=word.translation,
            example=word.example,
            difficulty=word.difficulty,
        )
