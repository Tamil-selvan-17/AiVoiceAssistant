"""
Gemini provider implementation, isolated behind the AIProvider interface --
no other module should know Gemini's request/response shapes.

Uses the Gemini REST API directly over httpx (rather than the google
SDK) to keep dependencies light and give us full control over timeouts
and error handling.
"""
import json
from typing import Any

import httpx

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.services.ai.base_provider import AIProvider, ChatMessage

logger = get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# NOTE: Google periodically retires Gemini model versions -- gemini-2.0-flash
# (this project's original default) was retired in mid-2026 and started
# returning 404s on every call. If you hit AI_PROVIDER_ERROR/404s in the
# server logs, check https://ai.google.dev/gemini-api/docs/deprecations for
# the current recommended model and update this default (or just set
# GEMINI_MODEL in your environment, which always overrides this).
_DEFAULT_MODEL = "gemini-2.5-flash"

_ANALYSIS_INSTRUCTIONS = (
    "You are an English-speaking coach. Analyze the exchange below and reply "
    "with ONLY a JSON object (no markdown fences, no commentary) with keys: "
    "grammar_score (0-100 integer), fluency_score (0-100 integer), "
    "corrections (array of {original, corrected, explanation}), "
    "new_words (array of {word, meaning, example, translation, difficulty}). "
    "For each new_word: 'translation' is that word translated into the "
    "learner's mother_language given in the input (empty string if mother "
    "tongue is English or you're unsure); 'difficulty' is one of "
    "'beginner'/'intermediate'/'advanced'. Only include words that are "
    "genuinely useful vocabulary for the learner's level -- not every word "
    "they used."
)


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str, model: str = "", timeout_seconds: int = 30):
        self._api_key = api_key
        self._model = model or _DEFAULT_MODEL
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "gemini"

    async def is_configured(self) -> bool:
        return bool(self._api_key)

    def _require_configured(self) -> None:
        if not self._api_key:
            raise AIProviderError(
                "Gemini is not configured. Set GEMINI_API_KEY.",
                "AI_PROVIDER_NOT_CONFIGURED",
            )

    @staticmethod
    def _to_gemini_contents(messages: list[ChatMessage]) -> list[dict[str, Any]]:
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        return contents

    async def generate_response(self, messages: list[ChatMessage], system_prompt: str) -> str:
        self._require_configured()
        url = f"{_BASE_URL}/models/{self._model}:generateContent"
        payload: dict[str, Any] = {
            "contents": self._to_gemini_contents(messages),
            "generationConfig": {"maxOutputTokens": 400, "temperature": 0.7},
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        data = await self._post(url, payload)
        return self._extract_text(data)

    async def analyze_conversation(self, conversation: dict[str, Any]) -> dict[str, Any]:
        self._require_configured()
        prompt = f"{_ANALYSIS_INSTRUCTIONS}\n\nConversation:\n{json.dumps(conversation)}"
        url = f"{_BASE_URL}/models/{self._model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 500, "temperature": 0.2},
        }
        data = await self._post(url, payload)
        text = self._extract_text(data)
        return self._safe_json(text)

    async def list_models(self) -> list[str]:
        if not self._api_key:
            return [self._model] if self._model else []

        url = f"{_BASE_URL}/models"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params={"key": self._api_key})
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            logger.error("gemini_list_models_failed")
            return [self._model] if self._model else []

        models = []
        for m in data.get("models", []):
            name = m.get("name", "")
            supported = m.get("supportedGenerationMethods", [])
            if "generateContent" in supported and name:
                models.append(name.split("/")[-1])
        return models or ([self._model] if self._model else [])

    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, params={"key": self._api_key}, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            logger.error("gemini_request_timeout")
            raise AIProviderError("Gemini request timed out.", "AI_PROVIDER_TIMEOUT") from exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "gemini_request_failed", extra={"status_code": exc.response.status_code}
            )
            raise AIProviderError("Gemini rejected the request.", "AI_PROVIDER_ERROR") from exc
        except httpx.HTTPError as exc:
            logger.error("gemini_request_error")
            raise AIProviderError("Unable to reach Gemini.", "AI_PROVIDER_ERROR") from exc

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        try:
            candidates = data["candidates"]
            parts = candidates[0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def _safe_json(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return {"raw_text": text, "parse_error": True}
