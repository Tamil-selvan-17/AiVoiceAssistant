"""
Tests for the Gemini-backed STT/TTS implementations. HTTP is mocked with
respx -- no real Gemini calls, no credits consumed (project spec §52).
"""
import base64
import wave
from io import BytesIO

import numpy as np
import pytest
import respx
from httpx import Response

from app.core.exceptions import AIProviderError
from app.services.voice.gemini_stt import GeminiSpeechToText
from app.services.voice.gemini_tts import GeminiTextToSpeech

_GEMINI_STT_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
_GEMINI_TTS_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash-preview-tts:generateContent"
)


def _make_wav(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    samples = np.zeros(int(sample_rate * duration_s), dtype=np.int16)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(samples.tobytes())
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# GeminiSpeechToText
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stt_requires_configuration():
    stt = GeminiSpeechToText(api_key="")
    with pytest.raises(AIProviderError):
        await stt.transcribe(_make_wav(), sample_rate=16000)


@pytest.mark.asyncio
async def test_stt_empty_audio_returns_empty_result_without_calling_api():
    stt = GeminiSpeechToText(api_key="fake-key")
    result = await stt.transcribe(b"", sample_rate=16000)
    assert result.text == ""
    assert result.detected_language == ""


@pytest.mark.asyncio
@respx.mock
async def test_stt_parses_transcript_and_language():
    respx.post(_GEMINI_STT_URL).mock(
        return_value=Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": '{"text": "I went to the office yesterday", "language": "en"}'}
                            ]
                        }
                    }
                ]
            },
        )
    )

    stt = GeminiSpeechToText(api_key="fake-key")
    result = await stt.transcribe(_make_wav(), sample_rate=16000)

    assert result.text == "I went to the office yesterday"
    assert result.detected_language == "en"


@pytest.mark.asyncio
@respx.mock
async def test_stt_falls_back_to_raw_text_on_malformed_json():
    respx.post(_GEMINI_STT_URL).mock(
        return_value=Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "not valid json"}]}}]},
        )
    )

    stt = GeminiSpeechToText(api_key="fake-key")
    result = await stt.transcribe(_make_wav(), sample_rate=16000)
    assert result.text == "not valid json"


@pytest.mark.asyncio
@respx.mock
async def test_stt_sends_audio_as_inline_base64():
    """Verify the actual request body matches Gemini's documented audio-input shape."""
    captured = {}

    def responder(request):
        import json

        captured["body"] = json.loads(request.content)
        return Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": '{"text": "hi", "language": "en"}'}]}}]},
        )

    respx.post(_GEMINI_STT_URL).mock(side_effect=responder)

    wav_bytes = _make_wav()
    stt = GeminiSpeechToText(api_key="fake-key")
    await stt.transcribe(wav_bytes, sample_rate=16000)

    parts = captured["body"]["contents"][0]["parts"]
    inline_part = next(p for p in parts if "inline_data" in p)
    assert inline_part["inline_data"]["mime_type"] == "audio/wav"
    assert base64.b64decode(inline_part["inline_data"]["data"]) == wav_bytes


@pytest.mark.asyncio
@respx.mock
async def test_stt_wraps_http_error():
    respx.post(_GEMINI_STT_URL).mock(return_value=Response(503, json={"error": "unavailable"}))

    stt = GeminiSpeechToText(api_key="fake-key")
    with pytest.raises(AIProviderError):
        await stt.transcribe(_make_wav(), sample_rate=16000)


# ---------------------------------------------------------------------------
# GeminiTextToSpeech
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tts_requires_configuration():
    tts = GeminiTextToSpeech(api_key="")
    with pytest.raises(AIProviderError):
        await tts.synthesize("hello")


@pytest.mark.asyncio
async def test_tts_empty_text_returns_silent_audio_without_calling_api():
    tts = GeminiTextToSpeech(api_key="fake-key")
    result = await tts.synthesize("   ")
    assert result.duration_seconds == 0.0
    assert result.wav_audio.startswith(b"RIFF")


@pytest.mark.asyncio
@respx.mock
async def test_tts_wraps_pcm_response_into_valid_wav():
    pcm_samples = np.zeros(16000, dtype=np.int16).tobytes()  # 1 second at 16kHz
    encoded = base64.b64encode(pcm_samples).decode("ascii")

    respx.post(_GEMINI_TTS_URL).mock(
        return_value=Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/L16;rate=16000",
                                        "data": encoded,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )
    )

    tts = GeminiTextToSpeech(api_key="fake-key")
    result = await tts.synthesize("Hello there.")

    assert result.sample_rate == 16000
    assert 0.9 < result.duration_seconds < 1.1
    assert result.wav_audio.startswith(b"RIFF")

    # The produced WAV must actually be readable and match the source PCM.
    with wave.open(BytesIO(result.wav_audio), "rb") as f:
        assert f.getframerate() == 16000
        assert f.getnchannels() == 1
        assert f.readframes(f.getnframes()) == pcm_samples


@pytest.mark.asyncio
@respx.mock
async def test_tts_raises_when_provider_returns_no_audio():
    respx.post(_GEMINI_TTS_URL).mock(
        return_value=Response(200, json={"candidates": [{"content": {"parts": []}}]})
    )

    tts = GeminiTextToSpeech(api_key="fake-key")
    with pytest.raises(AIProviderError):
        await tts.synthesize("Hello there.")


@pytest.mark.asyncio
@respx.mock
async def test_tts_wraps_http_error():
    respx.post(_GEMINI_TTS_URL).mock(return_value=Response(500, json={"error": "server error"}))

    tts = GeminiTextToSpeech(api_key="fake-key")
    with pytest.raises(AIProviderError):
        await tts.synthesize("Hello there.")
