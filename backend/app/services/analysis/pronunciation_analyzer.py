"""
Pronunciation analysis (project spec §34, goal 19: "Analyze pronunciation
where supported").

HONEST LIMITATION: real pronunciation assessment needs phoneme-level
acoustic analysis (forced alignment plus a per-phoneme confidence score --
the way Azure Speech's Pronunciation Assessment or similar specialized
APIs work). Gemini's generateContent audio transcription, used for STT in
this project (see gemini_stt.py), returns plain text only -- no per-word or
per-phoneme confidence. Fabricating a plausible-looking score from the
transcript text alone would be presenting a made-up number as if it
measured something it doesn't, which runs against this project's own
repeated stance on honesty (e.g. spec §18: "Do not claim perfect noise
cancellation").

So this module deliberately returns `score=None` with an explanatory note
instead of a fake number. Real pronunciation scoring would mean adding an
ASR provider that actually exposes phoneme-level confidence -- a provider
swap behind the same interface, not something to fake at this layer.
"""
from dataclasses import dataclass
from typing import Optional

NOT_SUPPORTED_NOTE = (
    "Pronunciation scoring isn't available yet -- it needs phoneme-level "
    "acoustic analysis that the current transcription provider doesn't "
    "expose. This will show a real score once a provider with pronunciation "
    "assessment is connected."
)


@dataclass
class PronunciationResult:
    score: Optional[int] = None
    note: str = NOT_SUPPORTED_NOTE


def analyze_pronunciation() -> PronunciationResult:
    return PronunciationResult()
