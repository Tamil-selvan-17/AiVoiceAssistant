"""
Voice pipeline endpoints: transcribe uploaded audio, synthesize speech from
text, and a lightweight VAD-only check. These are standalone REST endpoints
for exercising/testing the Phase 3 pipeline; the continuous conversation
loop (Phase 4) will call these same service classes over WebSocket rather
than duplicating this logic.
"""
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response

from app.core.config import Settings, get_settings
from app.core.exceptions import VoiceProcessingError
from app.schemas.voice import SynthesizeRequest
from app.services.voice.audio_processor import normalize_to_wav, wav_to_pcm16
from app.services.voice.gemini_stt import GeminiSpeechToText
from app.services.voice.gemini_tts import GeminiTextToSpeech
from app.services.voice.voice_activity_detector import VoiceActivityDetector

router = APIRouter(prefix="/api/voice", tags=["voice"])

_MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15MB -- a few minutes of compressed audio
_vad = VoiceActivityDetector(aggressiveness=2)


async def _read_and_normalize(file: UploadFile):
    raw = await file.read()
    if len(raw) > _MAX_AUDIO_BYTES:
        raise VoiceProcessingError("Audio file is too large.", "AUDIO_TOO_LARGE")

    format_hint = None
    if file.content_type:
        # e.g. "audio/webm;codecs=opus" -> "webm"
        format_hint = file.content_type.split("/")[-1].split(";")[0].strip() or None

    return normalize_to_wav(raw, source_format_hint=format_hint)


def _get_speech_to_text(settings: Settings) -> GeminiSpeechToText:
    return GeminiSpeechToText(
        api_key=settings.gemini_api_key,
        timeout_seconds=settings.ai_request_timeout_seconds,
    )


def _get_text_to_speech(settings: Settings, voice_name: str) -> GeminiTextToSpeech:
    return GeminiTextToSpeech(
        api_key=settings.gemini_api_key,
        voice_name=voice_name,
        timeout_seconds=settings.ai_request_timeout_seconds,
    )


@router.post("/vad-check")
async def vad_check(file: UploadFile = File(...)):
    """
    Run voice activity detection only, without transcribing. Useful for the
    client (or tests) to sanity-check a clip without spending an AI request
    on silence.
    """
    normalized = await _read_and_normalize(file)
    pcm, sample_rate = wav_to_pcm16(normalized.wav_bytes)
    result = _vad.analyze(pcm, sample_rate=sample_rate)

    return {
        "contains_speech": result.contains_speech,
        "speech_ratio": result.speech_ratio,
        "duration_seconds": round(normalized.duration_seconds, 3),
    }


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
):
    """
    Normalize the uploaded clip, run server-side VAD to avoid wasting an AI
    request on silence, then transcribe via Gemini if speech was detected.
    """
    normalized = await _read_and_normalize(file)
    pcm, sample_rate = wav_to_pcm16(normalized.wav_bytes)
    vad_result = _vad.analyze(pcm, sample_rate=sample_rate)

    if not vad_result.contains_speech:
        return {
            "text": "",
            "detected_language": "",
            "contains_speech": False,
            "speech_ratio": vad_result.speech_ratio,
            "duration_seconds": round(normalized.duration_seconds, 3),
        }

    stt = _get_speech_to_text(settings)
    result = await stt.transcribe(normalized.wav_bytes, sample_rate=normalized.sample_rate)

    return {
        "text": result.text,
        "detected_language": result.detected_language,
        "contains_speech": True,
        "speech_ratio": vad_result.speech_ratio,
        "duration_seconds": round(normalized.duration_seconds, 3),
    }


@router.post("/synthesize")
async def synthesize(
    request: SynthesizeRequest,
    settings: Settings = Depends(get_settings),
):
    """Synthesize speech for `text` and return raw WAV audio bytes."""
    tts = _get_text_to_speech(settings, request.voice_name)
    result = await tts.synthesize(request.text, speaking_speed=request.speaking_speed)

    return Response(
        content=result.wav_audio,
        media_type="audio/wav",
        headers={
            "X-Duration-Seconds": str(round(result.duration_seconds, 3)),
            "X-Sample-Rate": str(result.sample_rate),
        },
    )
