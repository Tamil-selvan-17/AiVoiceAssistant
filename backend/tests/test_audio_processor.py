"""
Tests for audio format normalization. These exercise real ffmpeg via pydub
(no mocking) -- webm/opus is converted to WAV exactly as a browser upload
would be, using synthetic audio generated in-test.
"""
import io
import wave

import numpy as np
import pytest

from app.core.exceptions import VoiceProcessingError
from app.services.voice.audio_processor import (
    normalize_to_wav,
    pcm16_to_wav,
    wav_to_pcm16,
)


def _make_wav_bytes(duration_s: float = 1.0, sample_rate: int = 48000, freq: int = 220) -> bytes:
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    samples = (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(samples.tobytes())
    return buffer.getvalue()


def test_normalize_wav_input_resamples_to_target_rate():
    raw = _make_wav_bytes(duration_s=1.0, sample_rate=48000)
    result = normalize_to_wav(raw, source_format_hint="wav")

    assert result.sample_rate == 16000
    assert 0.9 < result.duration_seconds < 1.1

    with wave.open(io.BytesIO(result.wav_bytes), "rb") as f:
        assert f.getframerate() == 16000
        assert f.getnchannels() == 1
        assert f.getsampwidth() == 2


def test_normalize_rejects_empty_audio():
    with pytest.raises(VoiceProcessingError):
        normalize_to_wav(b"", source_format_hint="wav")


def test_normalize_rejects_garbage_audio():
    with pytest.raises(VoiceProcessingError):
        normalize_to_wav(b"this is not audio data at all", source_format_hint="wav")


def test_pcm16_to_wav_roundtrip():
    pcm = (np.sin(np.linspace(0, 10, 1600)) * 10000).astype(np.int16).tobytes()
    wav_bytes = pcm16_to_wav(pcm, sample_rate=16000)

    recovered_pcm, sample_rate = wav_to_pcm16(wav_bytes)
    assert sample_rate == 16000
    assert recovered_pcm == pcm


def test_normalize_handles_stereo_input():
    # Build a 2-channel WAV and confirm it gets downmixed to mono.
    t = np.linspace(0, 1.0, 44100, endpoint=False)
    left = (0.3 * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    right = (0.3 * np.sin(2 * np.pi * 330 * t) * 32767).astype(np.int16)
    stereo = np.column_stack([left, right]).astype(np.int16)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(44100)
        f.writeframes(stereo.tobytes())

    result = normalize_to_wav(buffer.getvalue(), source_format_hint="wav")
    with wave.open(io.BytesIO(result.wav_bytes), "rb") as f:
        assert f.getnchannels() == 1
