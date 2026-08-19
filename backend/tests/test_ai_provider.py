"""
Tests for the AI provider abstraction. All HTTP calls are intercepted with
respx -- these tests never touch the real Gemini or NVIDIA APIs, so they're
safe to run without credentials and don't consume API credits (project spec
§52: "Mock external AI APIs. Tests must not consume real API credits.").
"""
import pytest
import respx
from httpx import Response

from app.core.config import Settings
from app.core.exceptions import AIProviderError
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.nvidia_provider import NvidiaProvider
from app.services.ai.provider_factory import ProviderFactory, UnknownProviderError


def _settings(**overrides) -> Settings:
    """
    Build a Settings instance for tests, bypassing any real .env file.

    Note: pydantic-settings' init-kwarg override only reliably wins over a
    dotenv file when kwargs are passed using the env-var alias (e.g.
    NVIDIA_API_KEY) rather than the Python field name (nvidia_api_key) --
    this keeps these tests correct even if a stray .env exists on disk.
    """
    base = dict(
        GEMINI_API_KEY="",
        GEMINI_MODEL="",
        NVIDIA_API_KEY="",
        NVIDIA_MODEL="",
        NVIDIA_BASE_URL="",
        AI_REQUEST_TIMEOUT_SECONDS=5,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


# ---------------------------------------------------------------------------
# ProviderFactory
# ---------------------------------------------------------------------------


def test_factory_creates_gemini_provider():
    provider = ProviderFactory.create("gemini", _settings(GEMINI_API_KEY="key123"))
    assert isinstance(provider, GeminiProvider)
    assert provider.provider_name == "gemini"


def test_factory_creates_nvidia_provider():
    provider = ProviderFactory.create("nvidia", _settings(NVIDIA_API_KEY="key123"))
    assert isinstance(provider, NvidiaProvider)
    assert provider.provider_name == "nvidia"


def test_factory_rejects_unknown_provider():
    with pytest.raises(UnknownProviderError):
        ProviderFactory.create("chatgpt", _settings())


def test_factory_reports_configured_providers():
    settings = _settings(GEMINI_API_KEY="abc", NVIDIA_API_KEY="")
    assert ProviderFactory.configured_providers(settings) == ["gemini"]

    settings = _settings(GEMINI_API_KEY="abc", NVIDIA_API_KEY="def")
    assert ProviderFactory.configured_providers(settings) == ["gemini", "nvidia"]

    settings = _settings(GEMINI_API_KEY="", NVIDIA_API_KEY="")
    assert ProviderFactory.configured_providers(settings) == []


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_requires_configuration():
    provider = GeminiProvider(api_key="")
    with pytest.raises(AIProviderError):
        await provider.generate_response([], "system prompt")


@pytest.mark.asyncio
@respx.mock
async def test_gemini_generate_response_parses_text():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    ).mock(
        return_value=Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "How was your day at work?"}]}}
                ]
            },
        )
    )

    provider = GeminiProvider(api_key="fake-key")
    reply = await provider.generate_response(
        [{"role": "user", "content": "Hello"}], "You are a friendly coach."
    )
    assert reply == "How was your day at work?"


@pytest.mark.asyncio
@respx.mock
async def test_gemini_analyze_conversation_parses_json():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    ).mock(
        return_value=Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"grammar_score": 80, "fluency_score": 75, '
                                        '"corrections": [], "new_words": []}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )
    )

    provider = GeminiProvider(api_key="fake-key")
    result = await provider.analyze_conversation({"text": "I go office yesterday"})
    assert result["grammar_score"] == 80
    assert result["fluency_score"] == 75


@pytest.mark.asyncio
@respx.mock
async def test_gemini_handles_non_json_analysis_gracefully():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    ).mock(
        return_value=Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "not json at all"}]}}]},
        )
    )

    provider = GeminiProvider(api_key="fake-key")
    result = await provider.analyze_conversation({"text": "hello"})
    assert result["parse_error"] is True
    assert result["raw_text"] == "not json at all"


@pytest.mark.asyncio
@respx.mock
async def test_gemini_wraps_http_error():
    respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
    ).mock(return_value=Response(500, json={"error": "server error"}))

    provider = GeminiProvider(api_key="fake-key")
    with pytest.raises(AIProviderError):
        await provider.generate_response([{"role": "user", "content": "hi"}], "prompt")


@pytest.mark.asyncio
@respx.mock
async def test_gemini_list_models_filters_by_supported_methods():
    respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
        return_value=Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-2.5-flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-001",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )
    )

    provider = GeminiProvider(api_key="fake-key")
    models = await provider.list_models()
    assert models == ["gemini-2.5-flash"]


# ---------------------------------------------------------------------------
# NvidiaProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nvidia_requires_configuration():
    provider = NvidiaProvider(api_key="")
    with pytest.raises(AIProviderError):
        await provider.generate_response([], "system prompt")


@pytest.mark.asyncio
@respx.mock
async def test_nvidia_generate_response_parses_text():
    respx.post("https://integrate.api.nvidia.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": "Tell me about your project."}}]},
        )
    )

    provider = NvidiaProvider(api_key="fake-key")
    reply = await provider.generate_response(
        [{"role": "user", "content": "I started a new project."}], "Be encouraging."
    )
    assert reply == "Tell me about your project."


@pytest.mark.asyncio
@respx.mock
async def test_nvidia_wraps_timeout_error():
    import httpx

    route = respx.post("https://integrate.api.nvidia.com/v1/chat/completions")
    route.mock(side_effect=httpx.TimeoutException("timed out"))

    provider = NvidiaProvider(api_key="fake-key")
    with pytest.raises(AIProviderError):
        await provider.generate_response([{"role": "user", "content": "hi"}], "prompt")


@pytest.mark.asyncio
@respx.mock
async def test_nvidia_list_models():
    respx.get("https://integrate.api.nvidia.com/v1/models").mock(
        return_value=Response(
            200,
            json={"data": [{"id": "meta/llama-3.1-8b-instruct"}, {"id": "meta/llama-3.1-70b-instruct"}]},
        )
    )

    provider = NvidiaProvider(api_key="fake-key")
    models = await provider.list_models()
    assert "meta/llama-3.1-8b-instruct" in models
    assert "meta/llama-3.1-70b-instruct" in models
