"""
Communication Confidence Score (project spec §35): an estimate derived from
communication signals (filler-word density, response length, response
latency) -- explicitly NOT a measurement of psychological confidence. The
project spec itself requires this distinction ("Do not claim that it
scientifically measures psychological confidence... Clearly label it as:
AI-generated practice metric"), so every caller surfacing this score must
keep that label attached rather than presenting a bare number.
"""
from dataclasses import dataclass
from typing import Optional

from app.services.analysis.fluency_analyzer import count_filler_words

LABEL = "AI-generated practice metric"


@dataclass
class ConfidenceResult:
    score: int
    label: str = LABEL


def analyze_confidence(user_text: str, response_latency_seconds: Optional[float]) -> ConfidenceResult:
    words = user_text.split()
    word_count = len(words)
    filler_count, _ = count_filler_words(user_text)

    score = 100

    if word_count > 0:
        filler_ratio = filler_count / word_count
        score -= min(30, round(filler_ratio * 150))

    if word_count <= 2:
        # A one/two-word answer reads as hesitant in a coaching-conversation
        # context, regardless of whether it was actually correct.
        score -= 25

    if response_latency_seconds is not None:
        if response_latency_seconds > 8:
            score -= 15
        elif response_latency_seconds > 4:
            score -= 5

    return ConfidenceResult(score=max(0, min(100, score)))
