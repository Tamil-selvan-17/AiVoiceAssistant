"""
NVIDIA provider implementation (OpenAI-compatible chat completions API via
NVIDIA NIM). Isolated behind the AIProvider interface -- kept fully separate
from GeminiProvider so either can change independently.
"""
import json
from typing import Any

import httpx

from app.core.exceptions import AIProviderError
from app.core.logging import get_logger
from app.services.ai.base_provider import AIProvider, ChatMessage

logger = get_logger(__name__)

_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
_DEFAULT_MODEL = "meta/llama-3.1-8b-instruct"

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


class NvidiaProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "",
        base_url: str = "",
        timeout_seconds: int = 30,
    ):
        self._api_key = api_key
        self._model = model or _DEFAULT_MODEL
        self._base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "nvidia"

    async def is_configured(self) -> bool:
        return bool(self._api_key)

    def _require_configured(self) -> None:
        if not self._api_key:
            raise AIProviderError(
                "NVIDIA is not configured. Set NVIDIA_API_KEY.",
                "AI_PROVIDER_NOT_CONFIGURED",
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _to_openai_messages(
        messages: list[ChatMessage], system_prompt: str
    ) -> list[dict[str, str]]:
        out = [{"role": "system", "content": system_prompt}] if system_prompt else []
        out.extend({"role": m["role"], "content": m["content"]} for m in messages)
        return out

    async def generate_response(self, messages: list[ChatMessage], system_prompt: str) -> str:
        self._require_configured()
        payload = {
            "model": self._model,
            "messages": self._to_openai_messages(messages, system_prompt),
            "max_tokens": 400,
            "temperature": 0.7,
        }
        data = await self._post("/chat/completions", payload)
        return self._extract_text(data)

    async def analyze_conversation(self, conversation: dict[str, Any]) -> dict[str, Any]:
        self._require_configured()
        prompt = f"{_ANALYSIS_INSTRUCTIONS}\n\nConversation:\n{json.dumps(conversation)}"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 500,
            "temperature": 0.2,
        }
        data = await self._post("/chat/completions", payload)
        text = self._extract_text(data)
        return self._safe_json(text)

    async def list_models(self) -> list[str]:
        if not self._api_key:
            return [self._model] if self._model else []

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(f"{self._base_url}/models", headers=self._headers())
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            logger.error("nvidia_list_models_failed")
            return [self._model] if self._model else []

        models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        return models or ([self._model] if self._model else [])

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}{path}", headers=self._headers(), json=payload
                )
                response.raise_for_status()
                return response.json()
        except httpx.TimeoutException as exc:
            logger.error("nvidia_request_timeout")
            raise AIProviderError("NVIDIA request timed out.", "AI_PROVIDER_TIMEOUT") from exc
        except httpx.HTTPStatusError as exc:
            logger.error(
                "nvidia_request_failed", extra={"status_code": exc.response.status_code}
            )
            raise AIProviderError("NVIDIA rejected the request.", "AI_PROVIDER_ERROR") from exc
        except httpx.HTTPError as exc:
            logger.error("nvidia_request_error")
            raise AIProviderError("Unable to reach NVIDIA.", "AI_PROVIDER_ERROR") from exc

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        try:
            return data["choices"][0]["message"]["content"].strip()
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
