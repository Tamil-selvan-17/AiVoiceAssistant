"""
Structured logging configuration.

Logs are emitted as single-line JSON so they are easy to ship to any log
aggregator. Secrets (API keys, tokens, passwords, raw audio) must never be
passed into these loggers -- callers are responsible for keeping sensitive
values out of log calls. See docs/DEVELOPER_GUIDE.md for the logging policy.
"""
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.config import get_settings

# Keys that should never appear in a log record, even if accidentally passed
# in `extra`. Values for these keys are redacted rather than dropped so the
# presence of an (attempted) leak is still visible in logs.
_REDACTED_KEYS = {
    "api_key",
    "gemini_api_key",
    "nvidia_api_key",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "raw_audio",
    "audio_bytes",
}


class JSONFormatter(logging.Formatter):
    """Formats log records as a single line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach any structured "extra" fields, redacting sensitive ones.
        reserved = set(vars(logging.makeLogRecord({})).keys())
        for key, value in vars(record).items():
            if key in reserved or key in ("message", "msg", "args"):
                continue
            if key.lower() in _REDACTED_KEYS:
                payload[key] = "***REDACTED***"
            else:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        import json

        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure root logging handlers. Call once at application startup."""
    settings = get_settings()

    root = logging.getLogger()
    root.setLevel(settings.log_level)

    # Avoid duplicate handlers if configure_logging() is called more than once
    # (e.g. under pytest re-imports).
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # Quiet down noisy third-party loggers by default.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)

    # httpx/httpcore log the full request URL at INFO level -- and Gemini's
    # REST API puts the API key in the URL query string (?key=...). Left at
    # INFO, every outbound Gemini call would print the key in plaintext,
    # directly violating this project's own "never log API keys" policy
    # (project spec §45). Raising these to WARNING is a hard requirement,
    # not just noise reduction.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
