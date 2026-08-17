"""
Audio format normalization utilities.

Browsers record with MediaRecorder in whatever codec they support (usually
audio/webm;codecs=opus or audio/ogg;codecs=opus) -- this module converts
whatever comes in into a normalized 16-bit PCM mono WAV at a fixed sample
rate, which is what both the VAD layer and Gemini's audio input expect.

ffmpeg (via pydub) does the heavy lifting. If ffmpeg isn't on PATH, audio
conversion fails loudly and clearly rather than silently producing garbage.
"""
import io
import shutil
import wave
from dataclasses import dataclass

from pydub import AudioSegment

from app.core.exceptions import VoiceProcessingError
from app.core.logging import get_logger

logger = get_logger(__name__)

# 16kHz mono is plenty for speech recognition and keeps payloads small.
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH_BYTES = 2  # 16-bit PCM


@dataclass
class NormalizedAudio:
    wav_bytes: bytes
    duration_seconds: float
    sample_rate: int = TARGET_SAMPLE_RATE
    channels: int = TARGET_CHANNELS


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise VoiceProcessingError(
            "Audio processing is unavailable on this server (ffmpeg not found).",
            "AUDIO_BACKEND_UNAVAILABLE",
        )


def normalize_to_wav(raw_audio: bytes, source_format_hint: str | None = None) -> NormalizedAudio:
    """
    Convert arbitrary browser-recorded audio bytes into normalized WAV.

    `source_format_hint` is an optional pydub format string (e.g. "webm",
    "ogg") derived from the upload's content-type. If omitted, pydub/ffmpeg
    will attempt to sniff the format from the byte stream itself.
    """
    _require_ffmpeg()

    if not raw_audio:
        raise VoiceProcessingError("No audio data was received.", "EMPTY_AUDIO")

    try:
        segment = AudioSegment.from_file(io.BytesIO(raw_audio), format=source_format_hint)
    except Exception as exc:  # pydub/ffmpeg raise various exceptions on bad input
        logger.error("audio_decode_failed", extra={"format_hint": source_format_hint})
        raise VoiceProcessingError(
            "Unable to decode the uploaded audio. Try a different format.",
            "AUDIO_DECODE_FAILED",
        ) from exc

    segment = (
        segment.set_frame_rate(TARGET_SAMPLE_RATE)
        .set_channels(TARGET_CHANNELS)
        .set_sample_width(TARGET_SAMPLE_WIDTH_BYTES)
    )

    buffer = io.BytesIO()
    segment.export(buffer, format="wav")
    wav_bytes = buffer.getvalue()

    return NormalizedAudio(
        wav_bytes=wav_bytes,
        duration_seconds=len(segment) / 1000.0,
    )


def pcm16_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """
    Wrap raw 16-bit PCM samples (e.g. from a TTS provider's audio stream)
    in a WAV container so browsers can play it directly with <audio>.
    """
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return buffer.getvalue()


def wav_to_pcm16(wav_bytes: bytes) -> tuple[bytes, int]:
    """Extract raw 16-bit PCM frames and sample rate from a WAV byte string."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        frames = wav_file.readframes(wav_file.getnframes())
        sample_rate = wav_file.getframerate()
    return frames, sample_rate
