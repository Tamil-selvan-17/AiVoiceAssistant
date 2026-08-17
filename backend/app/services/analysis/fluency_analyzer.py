"""
Fluency analysis (project spec §36-37): speaking rate and filler words.
Computed entirely from local signals (transcript text, audio duration) --
no AI call, so this can run on every turn for free, unlike grammar/
vocabulary analysis which needs one AI call per analyzed turn.

This is a heuristic estimate, not a validated speech-fluency assessment.
The thresholds below (WPM ranges, filler-ratio penalties) are a reasonable
first pass, not derived from any speech-science benchmark -- documented
here so nobody mistakes this for more than it is.
"""
import re
from dataclasses import dataclass

FILLER_WORDS = {"um", "uh", "actually", "like", "you know", "basically", "hmm", "er", "ah"}

_WORD_RE = re.compile(r"[A-Za-z']+")


def count_filler_words(text: str) -> tuple[int, list[str]]:
    """Returns (count, matched_fillers). Multi-word fillers ("you know") are
    matched as substrings; single-word fillers are matched as whole words."""
    lowered = text.lower()
    matches: list[str] = []

    for phrase in FILLER_WORDS:
        if " " in phrase:
            matches.extend([phrase] * lowered.count(phrase))

    words = _WORD_RE.findall(lowered)
    single_word_fillers = {f for f in FILLER_WORDS if " " not in f}
    matches.extend(w for w in words if w in single_word_fillers)

    return len(matches), matches


@dataclass
class FluencyResult:
    score: int
    words_per_minute: float
    filler_word_count: int
    note: str = ""


def analyze_fluency(user_text: str, duration_seconds: float) -> FluencyResult:
    words = _WORD_RE.findall(user_text)
    word_count = len(words)
    filler_count, _ = count_filler_words(user_text)

    duration_minutes = max(duration_seconds, 1.0) / 60
    wpm = round(word_count / duration_minutes, 1) if duration_minutes > 0 else 0.0

    score = 100
    if word_count > 0:
        filler_ratio = filler_count / word_count
        score -= min(40, round(filler_ratio * 200))

    if wpm > 0:
        if wpm < 70:
            score -= 15
        elif wpm > 200:
            score -= 10

    if word_count <= 2:
        # Too short an utterance to say much about fluency either way.
        score = min(score, 60)

    score = max(0, min(100, score))

    note = ""
    if filler_count >= 3:
        note = f'Try reducing filler words like "um" or "actually" ({filler_count} used).'
    elif wpm and wpm < 70:
        note = "Try speaking a little more -- natural pauses are fine."

    return FluencyResult(score=score, words_per_minute=wpm, filler_word_count=filler_count, note=note)
