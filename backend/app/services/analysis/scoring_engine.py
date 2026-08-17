"""
Combines per-turn analyzer outputs into the scores shown live in the chat
UI (spec §32 `score_update`) and the end-of-conversation summary (spec
§34, §38). Deliberately rule-based/deterministic rather than another AI
call -- keeps this cheap enough to run on every turn and easy to test
without mocking an AI provider.
"""
import re
from dataclasses import dataclass
from typing import Optional

from app.services.analysis.confidence_analyzer import ConfidenceResult
from app.services.analysis.fluency_analyzer import FluencyResult
from app.services.analysis.grammar_analyzer import GrammarResult
from app.services.analysis.pronunciation_analyzer import PronunciationResult
from app.services.analysis.vocabulary_analyzer import VocabularyResult

_WORD_RE = re.compile(r"[A-Za-z']+")

# A short list of very common English words, used only to estimate lexical
# diversity for the vocabulary score below -- not a dictionary or spellchecker.
_COMMON_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "i", "you", "he", "she",
    "it", "we", "they", "to", "and", "of", "in", "on", "at", "for", "with",
    "this", "that", "my", "your", "have", "has", "had", "do", "does", "did",
    "go", "went", "get", "got", "yes", "no", "okay", "ok", "so", "but",
}


@dataclass
class TurnScores:
    grammar_score: int
    fluency_score: int
    confidence_score: int
    vocabulary_score: int
    pronunciation_score: Optional[int]


def compute_vocabulary_score(user_text: str, new_word_count: int) -> int:
    """Heuristic: lexical diversity (share of non-common distinct words)
    plus a bonus for words flagged as genuinely new by the AI analysis."""
    words = [w.lower() for w in _WORD_RE.findall(user_text)]
    if not words:
        return 50

    distinct = set(words)
    uncommon = [w for w in distinct if w not in _COMMON_WORDS]
    diversity_ratio = len(uncommon) / max(1, len(words))

    score = 50 + round(diversity_ratio * 100 * 0.5) + min(20, new_word_count * 10)
    return max(0, min(100, score))


def compute_turn_scores(
    grammar: GrammarResult,
    fluency: FluencyResult,
    confidence: ConfidenceResult,
    vocabulary: VocabularyResult,
    pronunciation: PronunciationResult,
    user_text: str,
) -> TurnScores:
    return TurnScores(
        grammar_score=grammar.grammar_score,
        fluency_score=fluency.score,
        confidence_score=confidence.score,
        vocabulary_score=compute_vocabulary_score(user_text, len(vocabulary.words)),
        pronunciation_score=pronunciation.score,
    )


def compute_overall_score(scores: dict[str, Optional[int]]) -> int:
    """Averages whichever sub-scores are present; None entries (currently
    always pronunciation -- see pronunciation_analyzer) are excluded rather
    than treated as zero, so an unsupported metric can't drag the average
    down."""
    present = [v for v in scores.values() if v is not None]
    if not present:
        return 0
    return round(sum(present) / len(present))


def build_conversation_summary(
    *,
    grammar_scores: list[int],
    fluency_scores: list[int],
    confidence_scores: list[int],
    vocabulary_scores: list[int],
    total_filler_words: int,
    new_words_learned: int,
) -> dict:
    """Rule-based "what went well" / "improve next time" bullets (spec
    §38) -- no extra AI call, so this is safe to run on every conversation
    end regardless of MAX_DAILY_AI_REQUESTS."""

    def avg(values: list[int]) -> int:
        return round(sum(values) / len(values)) if values else 0

    grammar = avg(grammar_scores)
    fluency = avg(fluency_scores)
    confidence = avg(confidence_scores)
    vocabulary = avg(vocabulary_scores)
    overall = compute_overall_score(
        {"grammar": grammar, "fluency": fluency, "confidence": confidence, "vocabulary": vocabulary}
    )

    went_well: list[str] = []
    improve: list[str] = []

    if grammar >= 80:
        went_well.append("Strong grammar accuracy")
    elif grammar < 60:
        improve.append("Review common grammar patterns")

    if fluency >= 80:
        went_well.append("Smooth, natural speaking pace")
    elif fluency < 60:
        improve.append("Practice speaking a little more steadily")

    if confidence >= 80:
        went_well.append("Confident, decisive responses")
    elif confidence < 60:
        improve.append("Try answering with fuller sentences")

    if vocabulary >= 75:
        went_well.append("Good vocabulary variety")
    elif new_words_learned > 0:
        went_well.append(f"Learned {new_words_learned} new word{'s' if new_words_learned != 1 else ''}")

    if total_filler_words >= 5:
        improve.append(f"Reduce filler words (used {total_filler_words} times)")

    if not went_well:
        went_well.append("Completed the conversation -- good practice!")
    if not improve:
        improve.append("Keep practicing regularly to build on this")

    return {
        "overall_score": overall,
        "grammar_score": grammar,
        "fluency_score": fluency,
        "confidence_score": confidence,
        "vocabulary_score": vocabulary,
        "what_went_well": went_well,
        "improve_next_time": improve,
    }
