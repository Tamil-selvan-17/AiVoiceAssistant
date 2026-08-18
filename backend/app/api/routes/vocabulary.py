"""GET /api/vocabulary, DELETE /api/vocabulary/{id} (project spec §43)."""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.exceptions import NotFoundError
from app.db.mongodb import get_database
from app.schemas.analysis import VocabularyEntryResponse
from app.services.storage import vocabulary_repository as vocab_repo

router = APIRouter(prefix="/api/vocabulary", tags=["vocabulary"])


def _to_response(doc: dict) -> VocabularyEntryResponse:
    return VocabularyEntryResponse(
        id=doc["_id"],
        word=doc["word"],
        meaning=doc["meaning"],
        translation=doc.get("translation", ""),
        example=doc.get("example", ""),
        pronunciation=doc.get("pronunciation", ""),
        difficulty=doc.get("difficulty", "beginner"),
        first_seen=doc["first_seen"],
        review_count=doc.get("review_count", 1),
    )


@router.get("", response_model=list[VocabularyEntryResponse])
async def list_vocabulary(db: AsyncIOMotorDatabase = Depends(get_database)):
    words = await vocab_repo.list_vocabulary(db)
    return [_to_response(w) for w in words]


@router.delete("/{word_id}")
async def delete_vocabulary_word(word_id: str, db: AsyncIOMotorDatabase = Depends(get_database)):
    deleted = await vocab_repo.delete_word(db, word_id)
    if not deleted:
        raise NotFoundError("Vocabulary word not found.")
    return {"success": True, "message": "Word deleted."}
