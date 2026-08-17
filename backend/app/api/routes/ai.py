"""
AI provider discovery and model listing endpoints. These are read-only --
actual provider *usage* happens inside the conversation engine (Phase 4),
which obtains providers from ProviderFactory using the currently selected
settings, never by importing GeminiProvider/NvidiaProvider directly.
"""
from fastapi import APIRouter, Depends, Query

from app.core.config import Settings, get_settings
from app.services.ai.provider_factory import SUPPORTED_PROVIDERS, ProviderFactory

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/providers")
async def list_providers(settings: Settings = Depends(get_settings)):
    """List supported providers and whether each has credentials configured."""
    configured = set(ProviderFactory.configured_providers(settings))
    return {
        "providers": [
            {"id": name, "configured": name in configured} for name in SUPPORTED_PROVIDERS
        ]
    }


@router.get("/models")
async def list_models(
    provider: str = Query(..., description="Provider id: 'gemini' or 'nvidia'"),
    settings: Settings = Depends(get_settings),
):
    """
    List model identifiers available for a provider. If the provider isn't
    configured (no API key), returns just the configured default model
    name (or an empty list) rather than erroring, so the settings UI can
    still render a provider/model picker before keys are entered.
    """
    ai_provider = ProviderFactory.create(provider, settings)
    models = await ai_provider.list_models()
    return {"provider": provider, "models": models}
