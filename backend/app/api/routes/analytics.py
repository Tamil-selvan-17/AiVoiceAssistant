"""
GET /api/analytics/dashboard, GET /api/analytics/progress (project spec
§39-40, §43). Pure aggregation over already-stored data (conversations,
conversation_analysis, learning_progress) -- no AI calls, no extra cost.
"""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongodb import get_database
from app.schemas.analytics import (
    ConversationHistoryItem,
    DashboardResponse,
    MistakePattern,
    ProgressPoint,
    ProgressResponse,
)
from app.services.analysis.mistake_pattern_analyzer import find_frequent_mistakes
from app.services.storage import analysis_repository
from app.services.storage import conversation_repository as repo
from app.services.storage import learning_progress_repository as progress_repo

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _history_item(doc: dict) -> ConversationHistoryItem:
    summary = doc.get("analysis_summary") or {}
    return ConversationHistoryItem(
        id=doc["_id"],
        topic=doc["topic"],
        started_at=doc["started_at"],
        duration_seconds=doc.get("duration_seconds"),
        status=doc["status"],
        overall_score=summary.get("overall_score"),
        grammar_score=summary.get("grammar_score"),
        fluency_score=summary.get("fluency_score"),
        confidence_score=summary.get("confidence_score"),
        vocabulary_score=summary.get("vocabulary_score"),
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(db: AsyncIOMotorDatabase = Depends(get_database)):
    progress = await progress_repo.get_progress(db)
    conversations = await repo.list_conversations(db, limit=10)

    explanations: list[str] = []
    for conversation in conversations:
        entries = await analysis_repository.get_analysis_entries(db, conversation["_id"])
        for entry in entries:
            explanations.extend(c.get("explanation", "") for c in entry.get("corrections", []))

    frequent_mistakes = [
        MistakePattern(category=m.category, count=m.count, tip=m.tip)
        for m in find_frequent_mistakes(explanations)
    ]

    return DashboardResponse(
        total_conversations=progress.get("total_conversations", 0),
        total_speaking_seconds=progress.get("total_speaking_seconds", 0),
        avg_fluency=progress.get("avg_fluency", 0.0),
        avg_confidence=progress.get("avg_confidence", 0.0),
        avg_grammar=progress.get("avg_grammar", 0.0),
        avg_vocabulary=progress.get("avg_vocabulary", 0.0),
        vocabulary_learned_count=progress.get("vocabulary_learned_count", 0),
        current_streak_days=progress.get("current_streak_days", 0),
        recent_conversations=[_history_item(c) for c in conversations],
        frequent_mistakes=frequent_mistakes,
    )


@router.get("/progress", response_model=ProgressResponse)
async def get_progress(db: AsyncIOMotorDatabase = Depends(get_database)):
    """Chart data: one point per analyzed conversation, oldest first."""
    conversations = await repo.list_conversations(db, limit=50)
    conversations = list(reversed(conversations))  # list_conversations is newest-first

    points = []
    for conversation in conversations:
        summary = conversation.get("analysis_summary")
        if not summary:
            continue
        points.append(
            ProgressPoint(
                conversation_id=conversation["_id"],
                date=conversation.get("ended_at") or conversation["started_at"],
                overall_score=summary.get("overall_score", 0),
                fluency_score=summary.get("fluency_score", 0),
                confidence_score=summary.get("confidence_score", 0),
                grammar_score=summary.get("grammar_score", 0),
                vocabulary_score=summary.get("vocabulary_score", 0),
            )
        )

    return ProgressResponse(points=points)
