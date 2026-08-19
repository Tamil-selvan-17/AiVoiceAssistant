"""
Gemini-backed speech-to-text. Uses Gemini's multimodal `generateContent`
API with inline audio data -- Gemini accepts WAV directly, which is exactly
what `audio_processor.normalize_to_wav` produces, so no extra encoding step
is needed here.
"""
import base64
import json
import re

import httpx

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.services.voice.speech_to_text import SpeechToText, TranscriptionResult

logger = get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# See the matching NOTE in app/services/ai/gemini_provider.py -- using
# Google's "-latest" alias instead of a pinned version, since a pinned
# version has already 404'd twice in this project's history.
_DEFAULT_MODEL = "gemini-flash-latest"

_TRANSCRIBE_PROMPT = (
    "Transcribe the audio exactly as spoken, word for word, with no "
    "commentary. The speaker may mix English with Tamil, Telugu, Hindi, "
    "Malayalam, or Kannada -- transcribe each language in its own native "
    "script (do not translate). Respond with ONLY a JSON object of the "
    'form {"text": "<transcript>", "language": "<primary BCP-47 tag, e.g. '
    'en, ta, hi>"}. If no speech is audible, respond with '
    '{"text": "", "language": ""}.'
)


class GeminiSpeechToText(SpeechToText):
    def __init__(self, api_key: str, model: str = "", timeout_seconds: int = 30):
        self._api_key = api_key
        self._model = model or _DEFAULT_MODEL
        self._timeout = timeout_seconds

    async def transcribe(self, wav_audio: bytes, sample_rate: int) -> TranscriptionResult:
        if not self._api_key:
            raise AIProviderError(
                "Gemini is not configured. Set GEMINI_API_KEY.",
                "AI_PROVIDER_NOT_CONFIGURED",
            )
        if not wav_audio:
            return TranscriptionResult(text="", detected_language="")

        url = f"{_BASE_URL}/models/{self._model}:generateContent"
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": _TRANSCRIBE_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": base64.b64encode(wav_audio).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": 300, "temperature": 0.0},
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, params={"key": self._api_key}, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            logger.error("gemini_stt_timeout")
            raise AIProviderError(
                "Speech-to-text request timed out.", "AI_PROVIDER_TIMEOUT"
            ) from exc
        except httpx.HTTPStatusError as exc:
            logger.error("gemini_stt_failed", extra={"status_code": exc.response.status_code})
            raise AIProviderError(
                "Speech-to-text provider rejected the request.", "AI_PROVIDER_ERROR"
            ) from exc
        except httpx.HTTPError as exc:
            logger.error("gemini_stt_request_error")
            raise AIProviderError(
                "Unable to reach the speech-to-text provider.", "AI_PROVIDER_ERROR"
            ) from exc

        text = self._extract_text(data)
        parsed = self._safe_json(text)
        return TranscriptionResult(
            text=parsed.get("text", "").strip(),
            detected_language=parsed.get("language", "").strip(),
            raw_provider_response=data,
        )

    @staticmethod
    def _extract_text(data: dict) -> str:
        try:
            candidates = data["candidates"]
            parts = candidates[0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _safe_json(text: str) -> dict:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(json)?", "", cleaned).strip("`").strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            # Fall back to treating the raw model output as the transcript
            # rather than losing the utterance entirely.
            return {"text": cleaned, "language": ""}
