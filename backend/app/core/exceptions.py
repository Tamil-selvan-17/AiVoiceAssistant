"""
Application exceptions and global exception handlers.

Every error returned to a client follows the same shape:

    {
        "success": false,
        "message": "<safe, human-readable message>",
        "error_code": "<STABLE_UPPER_SNAKE_CASE_CODE>"
    }

Internal details (stack traces, raw exception text, DB errors) are logged
server-side via `app.core.logging` and never returned to the client.
"""
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    """Base class for all expected/handled application errors."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_ERROR"
    message: str = "Something went wrong. Please try again."

    def __init__(self, message: str | None = None, error_code: str | None = None):
        self.message = message or self.message
        self.error_code = error_code or self.error_code
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"
    message = "The requested resource was not found."


class ValidationAppError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VALIDATION_ERROR"
    message = "The provided input is invalid."


class RateLimitError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please slow down and try again shortly."


class AIProviderError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    error_code = "AI_PROVIDER_ERROR"
    message = "The AI provider is currently unavailable."


class VoiceProcessingError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    error_code = "VOICE_PROCESSING_ERROR"
    message = "Unable to process your voice input."


class DatabaseError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "DATABASE_ERROR"
    message = "A storage error occurred. Please try again."


def _error_body(message: str, error_code: str) -> dict:
    return {"success": False, "message": message, "error_code": error_code}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach global exception handlers to the FastAPI app."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "handled_app_error",
            extra={
                "error_code": exc.error_code,
                "path": request.url.path,
                "method": request.method,
            },
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.message, exc.error_code),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info(
            "request_validation_error",
            extra={"path": request.url.path, "errors": exc.errors()},
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_body(
                "One or more fields failed validation.", "VALIDATION_ERROR"
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(str(exc.detail), code),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Full details go to the server-side logs only -- never to the client.
        logger.error(
            "unhandled_exception",
            extra={"path": request.url.path, "method": request.method},
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(
                "An unexpected error occurred. Please try again.", "INTERNAL_ERROR"
            ),
        )
