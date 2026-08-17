"""
Provider-agnostic interface for chat-completion style AI providers.

Conversation-engine code (Phase 4) must depend only on this interface --
never import GeminiProvider or NvidiaProvider directly outside of
provider_factory.py. This is what keeps "the conversation service must not
contain Gemini-specific or NVIDIA-specific code" true (project spec, §11).
"""
from abc import ABC, abstractmethod
from typing import Any, TypedDict


class ChatMessage(TypedDict):
    role: str  # "user" | "assistant"
    content: str


class AIProvider(ABC):
    """Abstract base class every AI provider implementation must satisfy."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable machine-readable provider identifier, e.g. 'gemini'."""

    @abstractmethod
    async def generate_response(
        self,
        messages: list[ChatMessage],
        system_prompt: str,
    ) -> str:
        """
        Generate the next assistant message given conversation history.

        `messages` is ordered oldest-to-newest and uses only "user"/"assistant"
        roles. `system_prompt` carries persona + coaching instructions and is
        applied however is idiomatic for the underlying provider (a system
        role, a systemInstruction field, etc). Implementations should raise
        `app.core.exceptions.AIProviderError` on transport/auth failures.
        """

    @abstractmethod
    async def analyze_conversation(self, conversation: dict[str, Any]) -> dict[str, Any]:
        """
        Ask the provider to analyze a conversation (or a single exchange) and
        return a structured dict (grammar/fluency scores, corrections, new
        vocabulary). Malformed model output should be returned as
        {"raw_text": ..., "parse_error": True} rather than raised -- only
        actual transport/auth failures should raise AIProviderError.
        """

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return the list of model identifiers this provider can serve."""

    @abstractmethod
    async def is_configured(self) -> bool:
        """True if this provider has the credentials it needs to run."""
