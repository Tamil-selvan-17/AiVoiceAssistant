"""
Gemini-backed text-to-speech, using the Gemini TTS-capable model's
`generateContent` API with `responseModalities: ["AUDIO"]`. Gemini returns
raw 16-bit PCM (typically 24kHz mono) base64-encoded in the response, which
we wrap into a WAV container so the browser's <audio> element can play it
without any client-side decoding logic.
"""
import base64
import re

import httpx

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.services.voice.audio_processor import pcm16_to_wav
from app.services.voice.text_to_speech import SynthesisResult, TextToSpeech

logger = get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_DEFAULT_TTS_MODEL = "gemini-2.5-flash-preview-tts"
_DEFAULT_VOICE = "Kore"
_DEFAULT_SAMPLE_RATE = 24000


class GeminiTextToSpeech(TextToSpeech):
    def __init__(
        self,
        api_key: str,
        model: str = "",
        voice_name: str = _DEFAULT_VOICE,
        timeout_seconds: int = 30,
    ):
        self._api_key = api_key
        self._model = model or _DEFAULT_TTS_MODEL
        self._voice_name = voice_name
        self._timeout = timeout_seconds

    async def synthesize(self, text: str, speaking_speed: float = 1.0) -> SynthesisResult:
        if not self._api_key:
            raise AIProviderError(
                "Gemini is not configured. Set GEMINI_API_KEY.",
                "AI_PROVIDER_NOT_CONFIGURED",
            )
        if not text.strip():
            return SynthesisResult(
                wav_audio=pcm16_to_wav(b"", _DEFAULT_SAMPLE_RATE),
                sample_rate=_DEFAULT_SAMPLE_RATE,
                duration_seconds=0.0,
            )

        url = f"{_BASE_URL}/models/{self._model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": self._voice_name}}
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, params={"key": self._api_key}, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            logger.error("gemini_tts_timeout")
            raise AIProviderError(
                "Text-to-speech request timed out.", "AI_PROVIDER_TIMEOUT"
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.error("gemini_tts_failed", extra={"status_code": exc.response.status_code})
            raise AIProviderError(
                "Text-to-speech provider rejected the request.", "AI_PROVIDER_ERROR"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("gemini_tts_request_error")
            raise AIProviderError(
                "Unable to reach the text-to-speech provider.", "AI_PROVIDER_ERROR"
            ) from exc

        pcm_bytes, sample_rate = self._extract_pcm(data)
        if not pcm_bytes:
            raise AIProviderError(
                "Text-to-speech provider returned no audio.", "AI_PROVIDER_ERROR"
            )

        pcm_bytes = _apply_speed(pcm_bytes, sample_rate, speaking_speed)
        wav_bytes = pcm16_to_wav(pcm_bytes, sample_rate)
        duration_seconds = len(pcm_bytes) / 2 / sample_rate  # 16-bit mono

        return SynthesisResult(
            wav_audio=wav_bytes, sample_rate=sample_rate, duration_seconds=duration_seconds
        )

    @staticmethod
    def _extract_pcm(data: dict) -> tuple[bytes, int]:
        try:
            parts = data["candidates"][0]["content"]["parts"]
            inline = parts[0]["inlineData"]
            pcm_bytes = base64.b64decode(inline["data"])
            mime_type = inline.get("mimeType", "")
            match = re.search(r"rate=(\d+)", mime_type)
            sample_rate = int(match.group(1)) if match else _DEFAULT_SAMPLE_RATE
            return pcm_bytes, sample_rate
        except (KeyError, IndexError, TypeError, ValueError):
            return b"", _DEFAULT_SAMPLE_RATE


def _apply_speed(pcm_bytes: bytes, sample_rate: int, speaking_speed: float) -> bytes:
    """
    Naive playback-speed adjustment. Gemini's TTS API has no native speed
    parameter, so speeds other than 1.0x are approximated by resampling
    (which also shifts pitch slightly) -- acceptable for a coaching tool
    where 0.75x/1.25x are used for slow/fast practice, not studio audio.
    """
    if speaking_speed == 1.0 or not pcm_bytes:
        return pcm_bytes

    from pydub import AudioSegment

    segment = AudioSegment(
        data=pcm_bytes, sample_width=2, frame_rate=sample_rate, channels=1
    )
    sped_up = segment._spawn(
        segment.raw_data, overrides={"frame_rate": int(sample_rate * speaking_speed)}
    ).set_frame_rate(sample_rate)
    return sped_up.raw_data
