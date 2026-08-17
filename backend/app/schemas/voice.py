"""Schemas for /api/voice/* endpoints."""
from pydantic import BaseModel, Field


class TranscribeResponse(BaseModel):
    text: str
    detected_language: str
    contains_speech: bool
    speech_ratio: float
    duration_seconds: float


class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    speaking_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    voice_name: str = Field(default="Kore", max_length=50)


class VadCheckResponse(BaseModel):
    contains_speech: bool
    speech_ratio: float
    duration_seconds: float
