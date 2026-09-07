"""Per-user stored base resume + generated tailored variants.

The base resume is the canonical ``ResumeModel`` kept on the user document so the
browser extension (and repeat tailoring) can work without re-uploading a file.
Generated per-job PDF/DOCX variants are streamed into a GridFS bucket.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from app.database import get_db
from app.services.resume_model import ResumeModel

_VARIANT_BUCKET = "resume_variants"


def get_base_resume_model(user: dict[str, Any]) -> ResumeModel | None:
    raw = user.get("base_resume_model")
    if not isinstance(raw, dict):
        return None
    try:
        return ResumeModel(**raw)
    except Exception:
        return None


async def save_base_resume_model(user_id: ObjectId, model: ResumeModel) -> None:
    db = get_db()
    await db.users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "base_resume_model": model.model_dump(),
                "base_resume_updated_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        },
    )


async def clear_base_resume_model(user_id: ObjectId) -> None:
    db = get_db()
    await db.users.update_one(
        {"_id": user_id},
        {"$unset": {"base_resume_model": "", "base_resume_updated_at": ""}},
    )


def _bucket() -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(get_db(), bucket_name=_VARIANT_BUCKET)


async def store_resume_variant(
    *,
    user_id: ObjectId,
    job_hash: str,
    filename: str,
    content_type: str,
    data: bytes,
    meta: dict[str, Any] | None = None,
) -> str:
    """Replace any existing variant for (user, job) and return the new file id."""
    db = get_db()
    async for old in db[f"{_VARIANT_BUCKET}.files"].find(
        {"metadata.user_id": user_id, "metadata.job_hash": job_hash}
    ):
        await _bucket().delete(old["_id"])
    file_id = await _bucket().upload_from_stream(
        filename,
        data,
        metadata={
            "user_id": user_id,
            "job_hash": job_hash,
            "content_type": content_type,
            "created_at": datetime.now(UTC),
            **(meta or {}),
        },
    )
    return str(file_id)


async def read_resume_variant(
    *, user_id: ObjectId, variant_id: str
) -> tuple[bytes, str, str] | None:
    if not ObjectId.is_valid(variant_id):
        return None
    db = get_db()
    doc = await db[f"{_VARIANT_BUCKET}.files"].find_one({"_id": ObjectId(variant_id)})
    if not doc or doc.get("metadata", {}).get("user_id") != user_id:
        return None
    stream = await _bucket().open_download_stream(ObjectId(variant_id))
    data = await stream.read()
    meta = doc.get("metadata", {})
    return data, doc.get("filename") or "resume.pdf", meta.get("content_type") or "application/pdf"
