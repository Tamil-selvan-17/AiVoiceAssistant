"""
Single-call wrapper around AIProvider.analyze_conversation (built in Phase
2) for one user utterance. Both grammar_analyzer and vocabulary_analyzer
consume the SAME raw result from ONE AI call -- deliberately not two
separate calls -- since the analysis prompt already asks for grammar,
corrections, and vocabulary together (project spec §47, avoid unnecessary
AI requests).
"""
from dataclasses import dataclass, field
from typing import Any

from app.services.ai.base_provider import AIProvider


@dataclass
class RawTurnAnalysis:
    grammar_score: int
    fluency_score_hint: int  # the AI's own fluency guess; scoring_engine blends this with local signals
    corrections: list[dict[str, Any]] = field(default_factory=list)
    new_words: list[dict[str, Any]] = field(default_factory=list)
    parse_error: bool = False


def _clamp_score(value: Any, default: int = 70) -> int:
    try:
        score = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, min(100, score))


async def run_ai_turn_analysis(
    ai_provider: AIProvider,
    user_text: str,
    mother_language: str,
    target_language: str,
) -> RawTurnAnalysis:
    """
    Raises AIProviderError on transport/auth failure (same as any other
    AIProvider call) -- callers should decide whether that's fatal to the
    turn or just means "skip analysis for this turn."
    """
    conversation_payload = {
        "user_message": user_text,
        "mother_language": mother_language,
        "target_language": target_language,
    }
    raw = await ai_provider.analyze_conversation(conversation_payload)

    if raw.get("parse_error"):
        return RawTurnAnalysis(grammar_score=70, fluency_score_hint=70, parse_error=True)

    corrections = raw.get("corrections", [])
    new_words = raw.get("new_words", [])

    return RawTurnAnalysis(
        grammar_score=_clamp_score(raw.get("grammar_score")),
        fluency_score_hint=_clamp_score(raw.get("fluency_score")),
        corrections=corrections if isinstance(corrections, list) else [],
        new_words=new_words if isinstance(new_words, list) else [],
    )
