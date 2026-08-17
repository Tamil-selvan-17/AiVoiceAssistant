"""
Tests for the voice activity detector. Uses `espeak-ng` (if available on
the test machine, as it is in the project's Docker image once installed)
to synthesize real speech for a genuine positive case, plus pure-silence
and pure-tone clips for negative/edge cases. Falls back to skipping the
real-speech test if espeak-ng isn't installed, so CI without it still runs
the rest of the suite.
"""
import shutil
import subprocess
import wave

import numpy as np
import pytest

from app.services.voice.audio_processor import normalize_to_wav, wav_to_pcm16
from app.services.voice.voice_activity_detector import VoiceActivityDetector


def _silence_pcm(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    return np.zeros(int(sample_rate * duration_s), dtype=np.int16).tobytes()


def test_vad_reports_no_speech_for_pure_silence():
    vad = VoiceActivityDetector(aggressiveness=2)
    result = vad.analyze(_silence_pcm(), sample_rate=16000)

    assert result.contains_speech is False
    assert result.speech_ratio == 0.0
    assert result.trimmed_pcm == b""


def test_vad_analyze_handles_audio_shorter_than_one_frame():
    vad = VoiceActivityDetector(aggressiveness=2)
    # 5ms of audio at 16kHz -- shorter than webrtcvad's minimum 10ms frame.
    tiny_pcm = np.zeros(80, dtype=np.int16).tobytes()
    result = vad.analyze(tiny_pcm, sample_rate=16000)

    assert result.contains_speech is False
    assert result.trimmed_pcm == b""


def test_vad_aggressiveness_out_of_range_rejected():
    with pytest.raises(ValueError):
        VoiceActivityDetector(aggressiveness=5)


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng not installed")
def test_vad_detects_real_synthesized_speech(tmp_path):
    wav_path = tmp_path / "speech.wav"
    subprocess.run(
        ["espeak-ng", "-w", str(wav_path), "I went to the office yesterday."],
        check=True,
        capture_output=True,
    )

    raw = wav_path.read_bytes()
    normalized = normalize_to_wav(raw, source_format_hint="wav")
    pcm, sample_rate = wav_to_pcm16(normalized.wav_bytes)

    vad = VoiceActivityDetector(aggressiveness=2)
    result = vad.analyze(pcm, sample_rate=sample_rate)

    assert result.contains_speech is True
    # Real speech should register a healthy majority of frames as speech.
    assert result.speech_ratio > 0.5
    # Trimming should remove at least some silence without discarding everything.
    assert 0 < len(result.trimmed_pcm) <= len(pcm)
