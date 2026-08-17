"""
Centralized application configuration.

All runtime configuration is loaded from environment variables (or a local
.env file during development) via pydantic-settings. Nothing in this file
should ever contain a real secret -- defaults are empty strings / safe values
only. See backend/.env.example for the full list of supported variables.
"""
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, populated from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # --- Application ---
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_name: str = "ai-voice-assistant"
    app_version: str = "1.0.0"

    # --- MongoDB ---
    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_database: str = Field(default="ai_voice_assistant", alias="MONGODB_DATABASE")

    # --- Gemini ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="", alias="GEMINI_MODEL")

    # --- NVIDIA ---
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_model: str = Field(default="", alias="NVIDIA_MODEL")
    nvidia_base_url: str = Field(default="", alias="NVIDIA_BASE_URL")

    # --- CORS ---
    cors_origins: str = Field(default="http://localhost:8000", alias="CORS_ORIGINS")

    # --- Logging ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Cost / safety controls ---
    max_conversation_minutes: int = Field(default=30, alias="MAX_CONVERSATION_MINUTES")
    max_daily_ai_requests: int = Field(default=100, alias="MAX_DAILY_AI_REQUESTS")
    ai_request_timeout_seconds: int = Field(default=30, alias="AI_REQUEST_TIMEOUT_SECONDS")

    # --- Docs visibility (disable in production if desired) ---
    enable_api_docs: bool = Field(default=True, alias="ENABLE_API_DOCS")

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper

    @property
    def cors_origin_list(self) -> List[str]:
        """CORS_ORIGINS is a comma-separated string in the environment."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    def masked_gemini_key(self) -> str:
        return _mask_secret(self.gemini_api_key)

    def masked_nvidia_key(self) -> str:
        return _mask_secret(self.nvidia_api_key)


def _mask_secret(value: str) -> str:
    """Never return a full secret. Show only the last 4 characters."""
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


@lru_cache
def get_settings() -> Settings:
    """Settings are cached so the environment is only parsed once per process."""
    return Settings()
