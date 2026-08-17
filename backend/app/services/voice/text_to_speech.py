"""
Provider-agnostic text-to-speech interface. AI responses are spoken
automatically (project spec §22) -- keep voice settings/providers
swappable by depending only on this interface outside of
app/api/routes/voice.py.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SynthesisResult:
    wav_audio: bytes
    sample_rate: int
    duration_seconds: float


class TextToSpeech(ABC):
    @abstractmethod
    async def synthesize(self, text: str, speaking_speed: float = 1.0) -> SynthesisResult:
        """
        Synthesize speech audio for `text`, returned as WAV bytes so the
        frontend can play it directly via an <audio> element. Implementations
        should raise `app.core.exceptions.AIProviderError` on transport/auth
        failures.
        """
