"""
Grammar analysis (project spec §28-29): "Better Sentence Suggestions" and
inline corrections. This module does NOT call the AI itself -- it validates
and normalizes the grammar portion of the single shared
ai_turn_analysis.RawTurnAnalysis result, so grammar and vocabulary analysis
never cost two separate AI calls for the same utterance.
"""
from dataclasses import dataclass, field
from typing import Any

from app.services.analysis.ai_turn_analysis import RawTurnAnalysis


@dataclass
class Correction:
    original: str
    corrected: str
    explanation: str


@dataclass
class GrammarResult:
    grammar_score: int
    corrections: list[Correction] = field(default_factory=list)


def _valid_correction(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and isinstance(item.get("original"), str)
        and isinstance(item.get("corrected"), str)
        and item.get("original", "").strip()
        and item.get("corrected", "").strip()
        # Don't show a "correction" that doesn't actually change anything.
        and item["original"].strip() != item["corrected"].strip()
    )


def analyze_grammar(raw: RawTurnAnalysis) -> GrammarResult:
    corrections = [
        Correction(
            original=item["original"].strip(),
            corrected=item["corrected"].strip(),
            explanation=str(item.get("explanation", "")).strip(),
        )
        for item in raw.corrections
        if _valid_correction(item)
    ]
    return GrammarResult(grammar_score=raw.grammar_score, corrections=corrections)
