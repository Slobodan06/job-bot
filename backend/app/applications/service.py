"""Application-tracker operations shared by the member's own routes (``routes.py``)
and the manager/owner routes over every member's tracker (``admin_routes.py``).

Everything here works on an application document and its ``user_id`` (the member
who owns it), never on "the current user" — the routes decide who may act.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from bson import ObjectId
from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from app.applications.logic import (
    RESUME_MAX_BYTES,
    advances_status,
    application_doc_to_public,
    build_application_doc,
    build_applied_resume,
    detect_ats,
    is_valid_status,
    job_hash,
    resume_content_type,
)
from app.applications.schemas import (
    ApplicationPublic,
    ApplicationUpdateRequest,
    ApplicationUpsertRequest,
)
from app.database import get_db
from app.resume.store import delete_applied_resumes, read_applied_resume, store_applied_resume


def oid(value: str, what: str = "Application") -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail=f"{what} not found.")
    return ObjectId(value)


def to_public(doc: dict) -> ApplicationPublic:
    return ApplicationPublic(**application_doc_to_public(doc))


async def find_application(application_id: str, *, user_id: ObjectId | None = None) -> dict:
    """Load one application; ``user_id`` restricts it to that member (None = any member)."""
    query: dict[str, Any] = {"_id": oid(application_id)}
    if user_id is not None:
        query["user_id"] = user_id
    doc = await get_db().applications.find_one(query)
    if not doc:
        raise HTTPException(status_code=404, detail="Application not found.")
    return doc


def build_list_query(
    base: dict[str, Any], *, status: str | None, q: str | None, cursor: str | None
) -> dict[str, Any]:
    query = dict(base)
    if status and is_valid_status(status):
        query["status"] = status
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"company": rx}, {"job_title": rx}, {"location": rx}, {"job_url": rx}]
    if cursor and ObjectId.is_valid(cursor):
        query["_id"] = {"$lt": ObjectId(cursor)}
    return query


async def list_page(query: dict[str, Any], limit: int) -> tuple[list[dict], str | None]:
    docs = await get_db().applications.find(query).sort("_id", -1).limit(limit + 1).to_list(limit + 1)
    next_cursor = str(docs[limit]["_id"]) if len(docs) > limit else None
    return docs[:limit], next_cursor


async def status_counts(match: dict[str, Any]) -> tuple[int, dict[str, int]]:
    by_status: dict[str, int] = {}
    total = 0
    pipeline = [{"$match": match}, {"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    async for row in get_db().applications.aggregate(pipeline):
        by_status[row["_id"] or "detected"] = row["count"]
        total += row["count"]
    return total, by_status


async def upsert(user_id: ObjectId, body: ApplicationUpsertRequest, now: datetime) -> dict:
    db = get_db()
    doc = build_application_doc(user_id=user_id, payload=body.model_dump(), now=now)
    existing = await db.applications.find_one({"user_id": user_id, "job_hash": doc["job_hash"]})
    if not existing:
        result = await db.applications.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    updates: dict = {"updated_at": now}
    for key in ("ats", "company", "job_title", "location"):
        if doc[key] and not existing.get(key):
            updates[key] = doc[key]
    if doc["jd_text"] and len(doc["jd_text"]) > len(existing.get("jd_text") or ""):
        updates["jd_text"] = doc["jd_text"]
    if doc["notes"] and not existing.get("notes"):
        updates["notes"] = doc["notes"]
    # Only ever move forward (a re-detect or re-submit must not undo "interviewing").
    if advances_status(existing.get("status") or "", body.status):
        updates["status"] = body.status
    if body.status == "submitted" and not existing.get("submitted_at"):
        updates["submitted_at"] = doc["submitted_at"] or now
    await db.applications.update_one({"_id": existing["_id"]}, {"$set": updates})
    return await db.applications.find_one({"_id": existing["_id"]})


async def create_strict(user_id: ObjectId, body: ApplicationUpsertRequest) -> dict:
    """Manual insert: refuse (409) instead of merging into an existing record for the same job."""
    exists = await get_db().applications.find_one(
        {"user_id": user_id, "job_hash": job_hash(body.job_url)}, {"_id": 1}
    )
    if exists:
        raise HTTPException(status_code=409, detail="This job is already in the tracker.")
    return await upsert(user_id, body, datetime.now(UTC))


async def update(doc: dict, body: ApplicationUpdateRequest) -> dict:
    db = get_db()
    now = datetime.now(UTC)
    updates: dict = {"updated_at": now}

    if body.job_url is not None and body.job_url.strip() != (doc.get("job_url") or ""):
        url = body.job_url.strip()
        new_hash = job_hash(url)
        clash = await db.applications.find_one(
            {"user_id": doc["user_id"], "job_hash": new_hash, "_id": {"$ne": doc["_id"]}}, {"_id": 1}
        )
        if clash:
            raise HTTPException(status_code=409, detail="Another tracked job already uses this URL.")
        updates.update(job_url=url, job_hash=new_hash)
        detected = detect_ats(url)
        if detected != "other":
            updates["ats"] = detected
    for key in ("company", "job_title", "location"):
        value = getattr(body, key)
        if value is not None:
            updates[key] = value.strip()
    if body.status is not None:
        if not is_valid_status(body.status):
            raise HTTPException(status_code=400, detail="Unknown application status.")
        updates["status"] = body.status
        if body.status == "submitted" and not doc.get("submitted_at"):
            updates["submitted_at"] = now
    if body.submitted_at is not None:
        updates["submitted_at"] = body.submitted_at
    if body.notes is not None:
        updates["notes"] = body.notes.strip()

    await db.applications.update_one({"_id": doc["_id"]}, {"$set": updates})
    return await db.applications.find_one({"_id": doc["_id"]})


async def delete(doc: dict) -> None:
    await delete_applied_resumes(user_id=doc["user_id"], application_id=doc["_id"])
    await get_db().applications.delete_one({"_id": doc["_id"]})


# ---------------------------------------------------------------------------
# Applied resume
# ---------------------------------------------------------------------------


async def read_resume_upload(resume: UploadFile) -> tuple[bytes, str, str]:
    data = await resume.read()
    if not data:
        raise HTTPException(status_code=400, detail="Resume file is empty.")
    if len(data) > RESUME_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Resume file is larger than 5 MB.")
    filename = (resume.filename or "resume.pdf").strip()[:200]
    content_type = resume_content_type(filename, resume.content_type or "")
    if not content_type:
        raise HTTPException(status_code=400, detail="Resume must be a PDF, Word, RTF, ODT or text file.")
    return data, filename, content_type


async def attach_resume(doc: dict, *, data: bytes, filename: str, content_type: str, source: str) -> dict:
    """Store the applied resume (MongoDB GridFS) on an application, replacing any previous one."""
    db = get_db()
    now = datetime.now(UTC)
    file_id = await store_applied_resume(
        user_id=doc["user_id"],
        application_id=doc["_id"],
        filename=filename,
        content_type=content_type,
        data=data,
    )
    applied = build_applied_resume(
        file_id=file_id, filename=filename, content_type=content_type, size=len(data), source=source, now=now
    )
    await db.applications.update_one({"_id": doc["_id"]}, {"$set": {"applied_resume": applied, "updated_at": now}})
    return await db.applications.find_one({"_id": doc["_id"]})


async def replace_resume(doc: dict, resume: UploadFile) -> dict:
    data, filename, content_type = await read_resume_upload(resume)
    return await attach_resume(doc, data=data, filename=filename, content_type=content_type, source="uploaded_manually")


async def remove_resume(doc: dict) -> dict:
    db = get_db()
    await delete_applied_resumes(user_id=doc["user_id"], application_id=doc["_id"])
    await db.applications.update_one(
        {"_id": doc["_id"]}, {"$set": {"applied_resume": None, "updated_at": datetime.now(UTC)}}
    )
    return await db.applications.find_one({"_id": doc["_id"]})


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", filename) or "resume"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


async def resume_download(doc: dict) -> Response:
    file_id = (doc.get("applied_resume") or {}).get("file_id")
    found = await read_applied_resume(user_id=doc["user_id"], file_id=file_id or "")
    if not found:
        raise HTTPException(status_code=404, detail="No resume stored for this application.")
    data, filename, content_type = found
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": _content_disposition(filename)},
    )
