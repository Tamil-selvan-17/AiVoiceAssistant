"""CRUD endpoints for conversations (project spec §43)."""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import NotFoundError
from app.db.mongodb import get_database
from app.schemas.analysis import ConversationSummaryResponse
from app.schemas.conversation import ConversationCreate, ConversationResponse, MessageResponse
from app.services.analysis.pronunciation_analyzer import analyze_pronunciation
from app.services.analysis.scoring_engine import build_conversation_summary
from app.services.conversation.topic_manager import resolve_topic
from app.services.storage import analysis_repository, conversation_repository as repo
from app.services.storage import learning_progress_repository as progress_repo
from app.services.storage.settings_repository import get_settings_doc

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _to_response(doc: dict) -> ConversationResponse:
    return ConversationResponse(
        id=doc["_id"],
        topic=doc["topic"],
        difficulty=doc["difficulty"],
        mother_language=doc["mother_language"],
        target_language=doc["target_language"],
        ai_provider=doc["ai_provider"],
        ai_model=doc.get("ai_model", ""),
        started_at=doc["started_at"],
        ended_at=doc.get("ended_at"),
        duration_seconds=doc.get("duration_seconds"),
        status=doc["status"],
    )


def _message_to_response(doc: dict) -> MessageResponse:
    return MessageResponse(
        id=doc["_id"],
        conversation_id=doc["conversation_id"],
        speaker=doc["speaker"],
        text=doc["text"],
        language=doc.get("language", ""),
        timestamp=doc["timestamp"],
    )


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    payload: ConversationCreate, db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    Unset fields fall back to the global app_settings document (e.g. the
    learner's saved mother tongue / difficulty), matching the settings UI
    described in spec §42 rather than requiring every field on every call.
    """
    app_settings = await get_settings_doc(db)

    fields = {
        "topic": resolve_topic(payload.topic),
        "difficulty": payload.difficulty or app_settings.get("difficulty", "beginner"),
        "mother_language": payload.mother_language or app_settings.get("mother_language", "Tamil"),
        "target_language": payload.target_language
        or app_settings.get("target_language", "English"),
        "ai_provider": payload.ai_provider or app_settings.get("ai_provider", "gemini"),
        "ai_model": payload.ai_model or app_settings.get("ai_model", ""),
    }
    created = await repo.create_conversation(db, fields)
    return _to_response(created)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(db: AsyncIOMotorDatabase = Depends(get_database)):
    docs = await repo.list_conversations(db)
    return [_to_response(d) for d in docs]


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str, db: AsyncIOMotorDatabase = Depends(get_database)
):
    doc = await repo.get_conversation(db, conversation_id)
    if doc is None:
        raise NotFoundError("Conversation not found.")
    return _to_response(doc)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_conversation_messages(
    conversation_id: str, db: AsyncIOMotorDatabase = Depends(get_database)
):
    doc = await repo.get_conversation(db, conversation_id)
    if doc is None:
        raise NotFoundError("Conversation not found.")
    messages = await repo.get_messages(db, conversation_id)
    return [_message_to_response(m) for m in messages]


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str, db: AsyncIOMotorDatabase = Depends(get_database)
):
    deleted = await repo.delete_conversation(db, conversation_id)
    if not deleted:
        raise NotFoundError("Conversation not found.")
    return {"success": True, "message": "Conversation deleted."}


@router.post("/{conversation_id}/analyze", response_model=ConversationSummaryResponse)
async def analyze_conversation_endpoint(
    conversation_id: str, db: AsyncIOMotorDatabase = Depends(get_database)
):
    """
    End-of-conversation summary (project spec §34, §38): aggregates the
    per-turn analysis already computed live during the conversation (see
    conversation_manager._analyze_turn) rather than re-running AI analysis
    on every message again -- this endpoint is pure aggregation + rule-based
    summary text, no additional AI cost. Also ends the conversation (if not
    already ended) and folds the results into the rolling learning_progress
    aggregate that Phase 6's dashboard will read.
    """
    conversation = await repo.get_conversation(db, conversation_id)
    if conversation is None:
        raise NotFoundError("Conversation not found.")

    if conversation["status"] != "completed":
        conversation = await repo.end_conversation(db, conversation_id)

    entries = await analysis_repository.get_analysis_entries(db, conversation_id)
    messages = await repo.get_messages(db, conversation_id)

    total_filler_words = sum(e.get("filler_word_count", 0) for e in entries)
    new_words_learned = sum(len(e.get("new_words", [])) for e in entries)
    pronunciation = analyze_pronunciation()  # honestly unsupported -- see module docstring

    summary = build_conversation_summary(
        grammar_scores=[e["grammar_score"] for e in entries],
        fluency_scores=[e["fluency_score"] for e in entries],
        confidence_scores=[e["confidence_score"] for e in entries],
        vocabulary_scores=[e["vocabulary_score"] for e in entries],
        total_filler_words=total_filler_words,
        new_words_learned=new_words_learned,
    )

    await progress_repo.record_conversation_completion(
        db,
        duration_seconds=conversation.get("duration_seconds") or 0,
        fluency_score=summary["fluency_score"],
        confidence_score=summary["confidence_score"],
        grammar_score=summary["grammar_score"],
        vocabulary_score=summary["vocabulary_score"],
        new_words_learned=new_words_learned,
    )

    return ConversationSummaryResponse(
        conversation_id=conversation_id,
        topic=conversation["topic"],
        duration_seconds=conversation.get("duration_seconds") or 0,
        message_count=len(messages),
        overall_score=summary["overall_score"],
        fluency_score=summary["fluency_score"],
        confidence_score=summary["confidence_score"],
        grammar_score=summary["grammar_score"],
        vocabulary_score=summary["vocabulary_score"],
        pronunciation_score=pronunciation.score,
        pronunciation_note=pronunciation.note,
        filler_word_count=total_filler_words,
        new_words_learned=new_words_learned,
        what_went_well=summary["what_went_well"],
        improve_next_time=summary["improve_next_time"],
    )
