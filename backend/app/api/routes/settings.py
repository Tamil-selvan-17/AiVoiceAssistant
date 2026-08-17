"""
GET/PUT /api/settings -- a single global settings document. No auth, no
per-user scoping, since this is a single-user application.
"""
from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongodb import get_database
from app.schemas.settings import AppSettingsSchema, AppSettingsUpdate
from app.services.storage.settings_repository import get_settings_doc, update_settings_doc

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_response(doc: dict) -> AppSettingsSchema:
    doc = dict(doc)
    doc.pop("_id", None)
    return AppSettingsSchema(**doc)


@router.get("", response_model=AppSettingsSchema)
async def read_settings(db: AsyncIOMotorDatabase = Depends(get_database)):
    doc = await get_settings_doc(db)
    return _to_response(doc)


@router.put("", response_model=AppSettingsSchema)
async def update_settings(
    update: AppSettingsUpdate, db: AsyncIOMotorDatabase = Depends(get_database)
):
    doc = await update_settings_doc(db, update.model_dump())
    return _to_response(doc)
