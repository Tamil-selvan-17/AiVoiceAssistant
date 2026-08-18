"""
WebSocket endpoint for the continuous voice conversation loop (project spec
§16-17, §32). This file is orchestration/protocol only -- it calls straight
into `conversation_manager`, which is the same code path (and the same
Phase 2/3 service classes) the standalone REST endpoints use, so there's
exactly one implementation of "how a turn works."

Wire protocol:
  Client -> Server: one binary WebSocket frame per recorded utterance (the
    same audio blob VoiceController already produces in Phase 3 -- the
    server auto-detects the container format, same as /api/voice/transcribe).
  Server -> Client: JSON text frames for status/transcript/assistant/
    correction/vocabulary/score_update/error events (shapes follow spec
    §32), and a binary WAV frame for synthesized speech, always immediately
    preceded by a {"type": "audio_incoming", ...} text frame so the client
    knows a binary frame is coming next.
"""
import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.db.mongodb import get_database
from app.services.conversation import conversation_manager as manager
from app.services.storage import conversation_repository as repo

logger = get_logger(__name__)
router = APIRouter()

# Matches /api/voice/transcribe's own limit (app/api/routes/voice.py) --
# there's no reason a WebSocket-uploaded utterance should be allowed to be
# larger than the equivalent REST upload.
_MAX_WS_AUDIO_BYTES = 15 * 1024 * 1024

# Hobby-scale, single-user app -- this just guards against a runaway
# client (e.g. a bug that reconnects in a loop) exhausting server memory/
# file descriptors, not real multi-tenant capacity planning.
_MAX_CONCURRENT_CONNECTIONS = 20
_active_connections = 0
_connections_lock = asyncio.Lock()


async def _send_json(websocket: WebSocket, payload: dict) -> None:
    await websocket.send_text(json.dumps(payload))


async def _send_opening_result(websocket: WebSocket, result: manager.TurnResult) -> None:
    """
    The AI-speaks-first opening turn always has real content -- unlike
    _send_turn_result, there's no "silence, do nothing" case to handle here.
    """
    await _send_json(websocket, {"type": "assistant", "text": result.assistant_text})

    if result.assistant_audio_wav:
        await _send_json(
            websocket,
            {
                "type": "audio_incoming",
                "sample_rate": result.assistant_sample_rate,
                "byte_length": len(result.assistant_audio_wav),
            },
        )
        await websocket.send_bytes(result.assistant_audio_wav)

    await _send_json(websocket, {"type": "status", "status": "listening"})


async def _send_turn_result(websocket: WebSocket, result: manager.TurnResult) -> None:
    if result.conversation_ended:
        await _send_json(websocket, {"type": "status", "status": "ended", "reason": result.end_reason})
        return

    if not result.contains_speech:
        # Server-side VAD found nothing worth transcribing -- no transcript
        # event, just go back to listening (cost control, spec §47).
        await _send_json(websocket, {"type": "status", "status": "listening"})
        return

    await _send_json(
        websocket,
        {
            "type": "transcript",
            "speaker": "user",
            "text": result.user_text,
            "language": result.user_language,
        },
    )

    if not result.user_text:
        await _send_json(websocket, {"type": "status", "status": "listening"})
        return

    await _send_json(websocket, {"type": "assistant", "text": result.assistant_text})

    for correction in result.corrections:
        await _send_json(
            websocket,
            {
                "type": "correction",
                "original": correction.original,
                "corrected": correction.corrected,
                "explanation": correction.explanation,
            },
        )

    for word in result.new_words:
        await _send_json(
            websocket,
            {
                "type": "vocabulary",
                "word": word.word,
                "meaning": word.meaning,
                "translation": word.translation,
                "example": word.example,
                "difficulty": word.difficulty,
            },
        )

    if result.scores:
        await _send_json(websocket, {"type": "score_update", **result.scores})

    if result.assistant_audio_wav:
        await _send_json(
            websocket,
            {
                "type": "audio_incoming",
                "sample_rate": result.assistant_sample_rate,
                "byte_length": len(result.assistant_audio_wav),
            },
        )
        await websocket.send_bytes(result.assistant_audio_wav)

    await _send_json(websocket, {"type": "status", "status": "listening"})


@router.websocket("/ws/conversation/{conversation_id}")
async def conversation_websocket(
    websocket: WebSocket,
    conversation_id: str,
    db: AsyncIOMotorDatabase = Depends(get_database),
    settings: Settings = Depends(get_settings),
):
    global _active_connections

    async with _connections_lock:
        if _active_connections >= _MAX_CONCURRENT_CONNECTIONS:
            # Reject before accept() -- no sense completing the WS
            # handshake just to immediately close it.
            await websocket.close(code=1013)  # 1013 = "Try Again Later"
            logger.warning("conversation_websocket_connection_limit_reached")
            return
        _active_connections += 1

    try:
        await _run_conversation_websocket(websocket, conversation_id, db, settings)
    finally:
        async with _connections_lock:
            _active_connections -= 1


async def _run_conversation_websocket(
    websocket: WebSocket,
    conversation_id: str,
    db: AsyncIOMotorDatabase,
    settings: Settings,
) -> None:
    await websocket.accept()

    conversation = await repo.get_conversation(db, conversation_id)
    if conversation is None:
        await _send_json(
            websocket,
            {"type": "error", "message": "Conversation not found.", "error_code": "NOT_FOUND"},
        )
        await websocket.close(code=4404)
        return

    try:
        # AI speaks first, but only the very first time this conversation is
        # opened -- reconnecting to an in-progress conversation shouldn't
        # replay the greeting.
        existing_messages = await repo.get_messages(db, conversation_id)
        if not existing_messages:
            await _send_json(websocket, {"type": "status", "status": "processing"})
            try:
                opening = await manager.generate_opening_message(db, settings, conversation)
                await _send_opening_result(websocket, opening)
            except AppError as exc:
                logger.warning("conversation_opening_error", extra={"error_code": exc.error_code})
                await _send_json(
                    websocket, {"type": "error", "message": exc.message, "error_code": exc.error_code}
                )
                await _send_json(websocket, {"type": "status", "status": "listening"})
        else:
            await _send_json(websocket, {"type": "status", "status": "listening"})

        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            raw_audio = message.get("bytes")
            if raw_audio is None:
                # Ignore stray text frames (e.g. a client-side keepalive ping).
                continue

            if len(raw_audio) > _MAX_WS_AUDIO_BYTES:
                await _send_json(
                    websocket,
                    {
                        "type": "error",
                        "message": "Audio clip too large.",
                        "error_code": "PAYLOAD_TOO_LARGE",
                    },
                )
                await _send_json(websocket, {"type": "status", "status": "listening"})
                continue

            await _send_json(websocket, {"type": "status", "status": "processing"})

            try:
                # Re-fetch in case an earlier turn in this same connection
                # ended the conversation (time limit) or another client
                # changed it.
                conversation = await repo.get_conversation(db, conversation_id)
                if conversation is None:
                    await _send_json(
                        websocket,
                        {"type": "error", "message": "Conversation no longer exists.", "error_code": "NOT_FOUND"},
                    )
                    break

                result = await manager.handle_user_turn(db, settings, conversation, raw_audio)
            except AppError as exc:
                logger.warning("conversation_turn_error", extra={"error_code": exc.error_code})
                await _send_json(
                    websocket, {"type": "error", "message": exc.message, "error_code": exc.error_code}
                )
                await _send_json(websocket, {"type": "status", "status": "listening"})
                continue

            await _send_turn_result(websocket, result)
            if result.conversation_ended:
                break

    except WebSocketDisconnect:
        logger.info("conversation_websocket_disconnected", extra={"conversation_id": conversation_id})
