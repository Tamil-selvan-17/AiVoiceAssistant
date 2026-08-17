"""
Low-level audio helpers shared by the voice services. Kept dependency-free
(stdlib only) on purpose -- see app/services/voice/audio_processor.py for
the validation policy that uses these.
"""

# Formats MediaRecorder / common browsers can actually produce, plus wav
# for anything recorded/converted client-side or uploaded directly.
ALLOWED_AUDIO_MIME_TYPES = {
    "audio/webm",
    "audio/ogg",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/mpeg",
}


def is_allowed_mime_type(mime_type: str) -> bool:
    """Mime types may carry a codec suffix (e.g. 'audio/webm;codecs=opus')."""
    normalized = (mime_type or "").split(";")[0].strip().lower()
    return normalized in ALLOWED_AUDIO_MIME_TYPES


def human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"
