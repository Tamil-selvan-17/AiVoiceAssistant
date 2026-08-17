"""
Provider-agnostic speech-to-text interface. Conversation-engine code
(Phase 4) should depend only on this interface -- never import a concrete
STT implementation directly outside of app/api/routes/voice.py.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptionResult:
    text: str
    detected_language: str  # best-effort BCP-47-ish tag, e.g. "en", "ta"
    raw_provider_response: dict | None = None


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, wav_audio: bytes, sample_rate: int) -> TranscriptionResult:
        """
        Transcribe 16-bit PCM WAV audio. Implementations should raise
        `app.core.exceptions.AIProviderError` on transport/auth failures,
        and return an empty-text TranscriptionResult (not raise) if the
        provider genuinely heard nothing.
        """
