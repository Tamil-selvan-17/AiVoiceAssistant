"""
Factory that maps a provider name to a concrete AIProvider instance.

This is the ONLY place in the app that should import GeminiProvider or
NvidiaProvider directly. Conversation/analysis code (Phase 4+) depends on
the AIProvider interface and obtains instances through this factory, so
adding a third provider later means touching this file and nothing else
that consumes AIProvider.
"""
from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.ai.base_provider import AIProvider
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.nvidia_provider import NvidiaProvider

SUPPORTED_PROVIDERS = ("gemini", "nvidia")


class UnknownProviderError(AppError):
    status_code = 400
    error_code = "UNKNOWN_AI_PROVIDER"
    message = "Unknown AI provider requested."


class ProviderFactory:
    """Builds AIProvider instances from application settings."""

    @staticmethod
    def create(provider_name: str, settings: Settings, model_override: str = "") -> AIProvider:
        name = (provider_name or "").lower().strip()

        if name == "gemini":
            return GeminiProvider(
                api_key=settings.gemini_api_key,
                model=model_override or settings.gemini_model,
                timeout_seconds=settings.ai_request_timeout_seconds,
            )
        if name == "nvidia":
            return NvidiaProvider(
                api_key=settings.nvidia_api_key,
                model=model_override or settings.nvidia_model,
                base_url=settings.nvidia_base_url,
                timeout_seconds=settings.ai_request_timeout_seconds,
            )
        raise UnknownProviderError(
            f"Unknown AI provider '{provider_name}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    @staticmethod
    def configured_providers(settings: Settings) -> list[str]:
        """Providers that currently have credentials set, in a stable order."""
        available = []
        if settings.gemini_api_key:
            available.append("gemini")
        if settings.nvidia_api_key:
            available.append("nvidia")
        return available
