from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.applications.logic import (
    application_doc_to_public,
    build_application_doc,
    is_valid_status,
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

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=404, detail="Application not found.")
    return ObjectId(value)


@router.post("", response_model=ApplicationPublic)
async def upsert_application(
    body: ApplicationUpsertRequest,
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    db = get_db()
    now = datetime.now(UTC)
    doc = build_application_doc(user_id=user["_id"], payload=body.model_dump(), now=now)
    existing = await db.applications.find_one(
        {"user_id": user["_id"], "job_hash": doc["job_hash"]}
    )
    if existing:
        updates = {"updated_at": now}
        for key in ("ats", "company", "job_title", "location"):
            if doc[key] and not existing.get(key):
                updates[key] = doc[key]
        if doc["jd_text"] and len(doc["jd_text"]) > len(existing.get("jd_text") or ""):
            updates["jd_text"] = doc["jd_text"]
        # Only advance status forward on re-detect (never regress to "detected").
        if body.status != "detected" and is_valid_status(body.status):
            updates["status"] = body.status
            if body.status == "submitted" and not existing.get("submitted_at"):
                updates["submitted_at"] = now
        await db.applications.update_one({"_id": existing["_id"]}, {"$set": updates})
        merged = await db.applications.find_one({"_id": existing["_id"]})
        return ApplicationPublic(**application_doc_to_public(merged))

    result = await db.applications.insert_one(doc)
    doc["_id"] = result.inserted_id
    return ApplicationPublic(**application_doc_to_public(doc))


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
        rx = {"$regex": q.strip(), "$options": "i"}
        query["$or"] = [{"company": rx}, {"job_title": rx}, {"location": rx}]
    if cursor and ObjectId.is_valid(cursor):
        query["_id"] = {"$lt": ObjectId(cursor)}

    docs = await db.applications.find(query).sort("_id", -1).limit(limit + 1).to_list(limit + 1)
    next_cursor = str(docs[limit]["_id"]) if len(docs) > limit else None
    items = [ApplicationPublic(**application_doc_to_public(d)) for d in docs[:limit]]
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


@router.patch("/{application_id}", response_model=ApplicationPublic)
async def update_application(
    application_id: str,
    body: ApplicationUpdateRequest,
    user: dict = Depends(get_builder_user),
) -> ApplicationPublic:
    db = get_db()
    doc = await db.applications.find_one({"_id": _oid(application_id), "user_id": user["_id"]})
    if not doc:
        raise HTTPException(status_code=404, detail="Application not found.")
    updates: dict = {"updated_at": datetime.now(UTC)}
    if body.status is not None:
        if not is_valid_status(body.status):
            raise HTTPException(status_code=400, detail="Unknown application status.")
        updates["status"] = body.status
        if body.status == "submitted" and not doc.get("submitted_at"):
            updates["submitted_at"] = updates["updated_at"]
    if body.notes is not None:
        updates["notes"] = body.notes.strip()
    await db.applications.update_one({"_id": doc["_id"]}, {"$set": updates})
    merged = await db.applications.find_one({"_id": doc["_id"]})
    return ApplicationPublic(**application_doc_to_public(merged))


@router.delete("/{application_id}", status_code=204)
async def delete_application(
    application_id: str,
    user: dict = Depends(get_builder_user),
) -> None:
    db = get_db()
    result = await db.applications.delete_one(
        {"_id": _oid(application_id), "user_id": user["_id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Application not found.")
