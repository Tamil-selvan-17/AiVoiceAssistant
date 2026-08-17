"""
Server-side voice activity detection (VAD).

The browser does its own real-time VAD to decide when to stop recording
(see frontend/js/voice.js) so the user gets natural, responsive pauses
without a network round-trip. This module is the server-side backstop: it
double-checks that an uploaded clip actually contains speech (so we don't
burn an AI request transcribing silence) and trims leading/trailing
silence before handing audio to speech-to-text.

Uses WebRTC's VAD (via the `webrtcvad` bindings) which classifies fixed
20ms frames of 16-bit mono PCM as speech/non-speech -- fast, dependency-light,
and good enough for endpointing (it doesn't need to be perfect; STT is the
source of truth for what was actually said).
"""
from dataclasses import dataclass

import webrtcvad

from app.core.logging import get_logger

logger = get_logger(__name__)

_FRAME_MS = 30  # webrtcvad supports 10, 20, or 30ms frames
_SAMPLE_RATE = 16000
_BYTES_PER_SAMPLE = 2
_FRAME_BYTES = int(_SAMPLE_RATE * (_FRAME_MS / 1000.0) * _BYTES_PER_SAMPLE)


@dataclass
class VadResult:
    contains_speech: bool
    speech_ratio: float  # fraction of frames classified as speech, 0..1
    trimmed_pcm: bytes  # PCM with leading/trailing silence frames removed


class VoiceActivityDetector:
    """
    Wraps webrtcvad with a fixed 16kHz/mono/16-bit frame format (matching
    what `audio_processor.normalize_to_wav` always produces).

    `aggressiveness` ranges 0 (least aggressive about filtering non-speech)
    to 3 (most aggressive). 2 is a reasonable default for noisy mic input.
    """

    def __init__(self, aggressiveness: int = 2):
        if not 0 <= aggressiveness <= 3:
            raise ValueError("aggressiveness must be between 0 and 3")
        self._aggressiveness = aggressiveness

    def _frames(self, pcm: bytes) -> list[bytes]:
        frames = []
        for start in range(0, len(pcm) - _FRAME_BYTES + 1, _FRAME_BYTES):
            frames.append(pcm[start : start + _FRAME_BYTES])
        return frames

    def analyze(self, pcm: bytes, sample_rate: int = _SAMPLE_RATE) -> VadResult:
        """
        Analyze raw 16-bit mono PCM. Callers are responsible for passing
        audio already normalized to 16kHz (see audio_processor.py) -- other
        sample rates supported by webrtcvad (8000/32000/48000) will also
        work but frame sizing assumes 16kHz by default.

        A fresh `webrtcvad.Vad` is constructed per call rather than reused
        across analyses: the underlying WebRTC algorithm applies temporal
        smoothing across consecutive `is_speech()` calls, so reusing one
        instance across unrelated clips (e.g. a shared singleton serving
        many HTTP requests) lets one clip's energy bleed into the next
        clip's classification. Each clip is independent, so each gets its
        own VAD state.
        """
        vad = webrtcvad.Vad(self._aggressiveness)

        if sample_rate != _SAMPLE_RATE:
            frame_bytes = int(sample_rate * (_FRAME_MS / 1000.0) * _BYTES_PER_SAMPLE)
        else:
            frame_bytes = _FRAME_BYTES

        frames = [
            pcm[i : i + frame_bytes] for i in range(0, len(pcm) - frame_bytes + 1, frame_bytes)
        ]

        if not frames:
            return VadResult(contains_speech=False, speech_ratio=0.0, trimmed_pcm=b"")

        speech_flags = [vad.is_speech(f, sample_rate) for f in frames]
        speech_ratio = sum(speech_flags) / len(speech_flags)

        # Trim leading/trailing non-speech frames; keep interior silence
        # (natural pauses mid-sentence) intact -- see project spec §19:
        # "Do not immediately stop recording after a short pause."
        first_speech = next((i for i, is_speech in enumerate(speech_flags) if is_speech), None)
        last_speech = next(
            (i for i in range(len(speech_flags) - 1, -1, -1) if speech_flags[i]), None
        )

        if first_speech is None:
            trimmed_pcm = b""
        else:
            trimmed_pcm = b"".join(frames[first_speech : last_speech + 1])

        return VadResult(
            contains_speech=speech_ratio > 0.0,
            speech_ratio=round(speech_ratio, 4),
            trimmed_pcm=trimmed_pcm,
        )
