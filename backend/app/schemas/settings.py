"""
Schemas for the single global `app_settings` document (project spec §9).
There is one settings document for the whole app -- no per-user settings,
since there is no authentication.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Difficulty = Literal["beginner", "intermediate", "advanced"]
Provider = Literal["gemini", "nvidia"]


class AppSettingsSchema(BaseModel):
    mother_language: str = "Tamil"
    target_language: str = "English"
    difficulty: Difficulty = "beginner"
    ai_provider: Provider = "gemini"
    ai_model: str = ""
    show_corrections: bool = True
    show_vocabulary: bool = True
    show_tamil_translation: bool = True
    save_audio: bool = False
    auto_listen: bool = True
    noise_suppression: bool = True
    speaking_speed: float = Field(default=1.0, ge=0.5, le=2.0)


class AppSettingsUpdate(BaseModel):
    """All fields optional -- PUT /api/settings performs a partial update."""

    mother_language: Optional[str] = None
    target_language: Optional[str] = None
    difficulty: Optional[Difficulty] = None
    ai_provider: Optional[Provider] = None
    ai_model: Optional[str] = None
    show_corrections: Optional[bool] = None
    show_vocabulary: Optional[bool] = None
    show_tamil_translation: Optional[bool] = None
    save_audio: Optional[bool] = None
    auto_listen: Optional[bool] = None
    noise_suppression: Optional[bool] = None
    speaking_speed: Optional[float] = Field(default=None, ge=0.5, le=2.0)
