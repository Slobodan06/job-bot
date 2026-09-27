import json
import re
from datetime import UTC, datetime
from urllib.parse import quote

from bson import ObjectId
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import ValidationError

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
    ApplicationListResponse,
    ApplicationPublic,
    ApplicationStatsResponse,
    ApplicationUpdateRequest,
    ApplicationUpsertRequest,
)
from app.auth.dependencies import get_builder_user
from app.database import get_db
from app.resume.store import (
    delete_applied_resumes,
    read_applied_resume,
    read_resume_variant,
    store_applied_resume,
)

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="Application not found.")
    return ObjectId(value)


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r'[^A-Za-z0-9._ -]+', "_", filename) or "resume"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _public(doc: dict) -> ApplicationPublic:
    return ApplicationPublic(**application_doc_to_public(doc))


async def _owned(application_id: str, user: dict) -> dict:
    doc = await get_db().applications.find_one({"_id": _oid(application_id), "user_id": user["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Application not found.")
    return doc


async def _upsert(user: dict, body: ApplicationUpsertRequest, now: datetime) -> dict:
    db = get_db()
    doc = build_application_doc(user_id=user["_id"], payload=body.model_dump(), now=now)
    existing = await db.applications.find_one({"user_id": user["_id"], "job_hash": doc["job_hash"]})
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


async def _read_resume_upload(resume: UploadFile) -> tuple[bytes, str, str]:
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


async def _attach_resume(
    doc: dict,
    *,
    data: bytes,
    filename: str,
    content_type: str,
    source: str,
) -> dict:
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
        file_id=file_id,
        filename=filename,
        content_type=content_type,
        size=len(data),
        source=source,
        now=now,
    )
    await db.applications.update_one(
        {"_id": doc["_id"]}, {"$set": {"applied_resume": applied, "updated_at": now}}
    )
    return await db.applications.find_one({"_id": doc["_id"]})


# ---------------------------------------------------------------------------
# Create / list / stats
# ---------------------------------------------------------------------------


@router.post("", response_model=ApplicationPublic)
async def upsert_application(
    body: ApplicationUpsertRequest,
    strict: bool = Query(default=False, description="Fail with 409 instead of merging duplicates."),
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    if strict:
        exists = await get_db().applications.find_one(
            {"user_id": user["_id"], "job_hash": job_hash(body.job_url)}, {"_id": 1}
        )
        if exists:
            raise HTTPException(status_code=409, detail="This job is already in your tracker.")
    return _public(await _upsert(user, body, datetime.now(UTC)))


@router.post("/submitted", response_model=ApplicationPublic)
async def record_submitted_application(
    payload: str = Form(..., description="ApplicationUpsertRequest as JSON"),
    resume: UploadFile | None = File(default=None),
    resume_variant_id: str = Form(default=""),
    resume_source: str = Form(default=""),
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    """Called by the extension once the site confirms the application was sent.

    Records the job as ``submitted`` together with the resume that went out with
    it — either the file the user picked on the page (uploaded here) or the
    JobBot-generated variant the extension attached (referenced by id) — stored
    in MongoDB alongside the application.
    """
    try:
        body = ApplicationUpsertRequest(**{**json.loads(payload), "status": "submitted"})
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid payload: {exc}") from exc

    file: tuple[bytes, str, str] | None = None
    source = resume_source or "selected_on_page"
    if resume is not None and (resume.filename or "").strip():
        file = await _read_resume_upload(resume)
    elif resume_variant_id:
        found = await read_resume_variant(user_id=user["_id"], variant_id=resume_variant_id)
        if found:
            file = found
            source = "attached_by_extension"

    doc = await _upsert(user, body, datetime.now(UTC))
    if file:
        data, filename, content_type = file
        doc = await _attach_resume(
            doc,
            data=data,
            filename=filename,
            content_type=content_type,
            source=source,
        )
    return _public(doc)


@router.get("", response_model=ApplicationListResponse)
async def list_applications(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    user: dict = Depends(get_builder_user),
) -> ApplicationListResponse:
    db = get_db()
    query: dict = {"user_id": user["_id"]}
    if status and is_valid_status(status):
        query["status"] = status
    if q:
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"company": rx}, {"job_title": rx}, {"location": rx}, {"job_url": rx}]
    if cursor and ObjectId.is_valid(cursor):
        query["_id"] = {"$lt": ObjectId(cursor)}

    docs = await db.applications.find(query).sort("_id", -1).limit(limit + 1).to_list(limit + 1)
    next_cursor = str(docs[limit]["_id"]) if len(docs) > limit else None
    items = [_public(d) for d in docs[:limit]]
    return ApplicationListResponse(items=items, next_cursor=next_cursor)


@router.get("/stats", response_model=ApplicationStatsResponse)
async def application_stats(user: dict = Depends(get_builder_user)) -> ApplicationStatsResponse:
    db = get_db()
    by_status: dict[str, int] = {}
    total = 0
    pipeline = [
        {"$match": {"user_id": user["_id"]}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    async for row in db.applications.aggregate(pipeline):
        by_status[row["_id"] or "detected"] = row["count"]
        total += row["count"]
    return ApplicationStatsResponse(total=total, by_status=by_status)


# ---------------------------------------------------------------------------
# Read / update / delete one
# ---------------------------------------------------------------------------


@router.get("/{application_id}", response_model=ApplicationPublic)
async def get_application(application_id: str, user: dict = Depends(get_builder_user)) -> ApplicationPublic:
    return _public(await _owned(application_id, user))


@router.patch("/{application_id}", response_model=ApplicationPublic)
async def update_application(
    application_id: str,
    body: ApplicationUpdateRequest,
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    db = get_db()
    doc = await _owned(application_id, user)
    now = datetime.now(UTC)
    updates: dict = {"updated_at": now}

    if body.job_url is not None and body.job_url.strip() != (doc.get("job_url") or ""):
        url = body.job_url.strip()
        new_hash = job_hash(url)
        clash = await db.applications.find_one(
            {"user_id": user["_id"], "job_hash": new_hash, "_id": {"$ne": doc["_id"]}}, {"_id": 1}
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

    return _public(await db.applications.find_one({"_id": doc["_id"]}))


@router.delete("/{application_id}", status_code=204)
async def delete_application(
    application_id: str,
    user: dict = Depends(get_builder_user),
) -> None:
    doc = await _owned(application_id, user)
    await delete_applied_resumes(user_id=user["_id"], application_id=doc["_id"])
    await get_db().applications.delete_one({"_id": doc["_id"]})


# ---------------------------------------------------------------------------
# Applied resume
# ---------------------------------------------------------------------------


@router.get("/{application_id}/resume")
async def download_applied_resume(application_id: str, user: dict = Depends(get_builder_user)) -> Response:
    doc = await _owned(application_id, user)
    file_id = (doc.get("applied_resume") or {}).get("file_id")
    found = await read_applied_resume(user_id=user["_id"], file_id=file_id or "")
    if not found:
        raise HTTPException(status_code=404, detail="No resume stored for this application.")
    data, filename, content_type = found
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.put("/{application_id}/resume", response_model=ApplicationPublic)
async def replace_applied_resume(
    application_id: str,
    resume: UploadFile = File(...),
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    doc = await _owned(application_id, user)
    data, filename, content_type = await _read_resume_upload(resume)
    doc = await _attach_resume(
        doc,
        data=data,
        filename=filename,
        content_type=content_type,
        source="uploaded_manually",
    )
    return _public(doc)


@router.delete("/{application_id}/resume", response_model=ApplicationPublic)
async def remove_applied_resume(application_id: str, user: dict = Depends(get_builder_user)) -> ApplicationPublic:
    db = get_db()
    doc = await _owned(application_id, user)
    await delete_applied_resumes(user_id=user["_id"], application_id=doc["_id"])
    await db.applications.update_one(
        {"_id": doc["_id"]}, {"$set": {"applied_resume": None, "updated_at": datetime.now(UTC)}}
    )
    return _public(await db.applications.find_one({"_id": doc["_id"]}))

