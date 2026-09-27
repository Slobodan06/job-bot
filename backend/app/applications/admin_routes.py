"""Manager view over every member's application tracker.

Managers are the site owner plus any member the owner granted the
``can_manage_applications`` permission (Members page → "Team tracker").

Same operations as a member has on their own tracker — list, create, edit,
delete, and manage the applied resume — but across all members, plus a
per-member summary of how their job search is going.
"""
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.applications import service
from app.applications.schemas import (
    ApplicationStatsResponse,
    ApplicationUpdateRequest,
    ApplicationUpsertRequest,
    MemberApplicationListResponse,
    MemberApplicationPublic,
    MemberRef,
    MemberTrackingSummary,
)
from app.auth.dependencies import get_applications_manager, public_user
from app.database import get_db

router = APIRouter(prefix="/api/admin/applications", tags=["admin"])


def _member_ref(user: dict | None, user_id: Any) -> MemberRef:
    if not user:
        return MemberRef(id=str(user_id), name="(deleted member)")
    return MemberRef(id=str(user["_id"]), name=user.get("name") or "", email=user.get("email") or "")


async def _members_by_id(user_ids: set[Any]) -> dict[Any, dict]:
    if not user_ids:
        return {}
    cursor = get_db().users.find({"_id": {"$in": list(user_ids)}}, {"name": 1, "email": 1})
    return {u["_id"]: u async for u in cursor}


async def _with_member(doc: dict, member: dict | None = None) -> MemberApplicationPublic:
    if member is None:
        member = await get_db().users.find_one({"_id": doc["user_id"]}, {"name": 1, "email": 1})
    return MemberApplicationPublic(
        **service.to_public(doc).model_dump(), member=_member_ref(member, doc["user_id"])
    )


async def _member(member_id: str) -> dict:
    doc = await get_db().users.find_one({"_id": service.oid(member_id, "Member")})
    if not doc:
        raise HTTPException(status_code=404, detail="Member not found.")
    return doc


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=list[MemberTrackingSummary])
async def tracking_summary(_manager: dict = Depends(get_applications_manager)) -> list[MemberTrackingSummary]:
    """One row per member: how many jobs they've tracked, by status, and when they last applied."""
    db = get_db()
    pipeline = [
        {
            "$group": {
                "_id": {"user_id": "$user_id", "status": "$status"},
                "count": {"$sum": 1},
                "last_applied_at": {"$max": "$submitted_at"},
                "last_activity_at": {"$max": "$updated_at"},
            }
        }
    ]
    per_user: dict[Any, dict] = {}
    async for row in db.applications.aggregate(pipeline):
        uid = row["_id"]["user_id"]
        agg = per_user.setdefault(
            uid, {"total": 0, "by_status": {}, "last_applied_at": None, "last_activity_at": None}
        )
        status = row["_id"].get("status") or "detected"
        agg["by_status"][status] = agg["by_status"].get(status, 0) + row["count"]
        agg["total"] += row["count"]
        for key in ("last_applied_at", "last_activity_at"):
            if row.get(key) and (agg[key] is None or row[key] > agg[key]):
                agg[key] = row[key]

    rows: list[MemberTrackingSummary] = []
    async for user in db.users.find({}).sort("created_at", -1):
        pub = public_user(user)
        agg = per_user.get(user["_id"], {})
        rows.append(
            MemberTrackingSummary(
                member=_member_ref(user, user["_id"]),
                role=pub["role"],
                has_access=pub["has_access"],
                total=agg.get("total", 0),
                by_status=agg.get("by_status", {}),
                last_applied_at=agg.get("last_applied_at"),
                last_activity_at=agg.get("last_activity_at"),
            )
        )
    # Most active job seekers first; members with no applications keep sign-up order.
    rows.sort(key=lambda r: r.total == 0)
    return rows


@router.get("", response_model=MemberApplicationListResponse)
async def list_member_applications(
    member_id: str | None = Query(default=None, description="Only this member's applications"),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
    _manager: dict = Depends(get_applications_manager),
) -> MemberApplicationListResponse:
    base: dict[str, Any] = {}
    if member_id:
        base["user_id"] = service.oid(member_id, "Member")
    query = service.build_list_query(base, status=status, q=q, cursor=cursor)
    docs, next_cursor = await service.list_page(query, limit)
    members = await _members_by_id({d["user_id"] for d in docs})
    items = [
        MemberApplicationPublic(
            **service.to_public(d).model_dump(), member=_member_ref(members.get(d["user_id"]), d["user_id"])
        )
        for d in docs
    ]
    return MemberApplicationListResponse(items=items, next_cursor=next_cursor)


@router.get("/stats", response_model=ApplicationStatsResponse)
async def member_application_stats(
    member_id: str | None = Query(default=None),
    _manager: dict = Depends(get_applications_manager),
) -> ApplicationStatsResponse:
    match = {"user_id": service.oid(member_id, "Member")} if member_id else {}
    total, by_status = await service.status_counts(match)
    return ApplicationStatsResponse(total=total, by_status=by_status)


# ---------------------------------------------------------------------------
# Create / read / update / delete
# ---------------------------------------------------------------------------


@router.post("", response_model=MemberApplicationPublic)
async def create_member_application(
    body: ApplicationUpsertRequest,
    member_id: str = Query(..., description="Member whose tracker gets the job"),
    _manager: dict = Depends(get_applications_manager),
) -> MemberApplicationPublic:
    member = await _member(member_id)
    return await _with_member(await service.create_strict(member["_id"], body), member)


@router.get("/{application_id}", response_model=MemberApplicationPublic)
async def get_member_application(
    application_id: str, _manager: dict = Depends(get_applications_manager)
) -> MemberApplicationPublic:
    return await _with_member(await service.find_application(application_id))


@router.patch("/{application_id}", response_model=MemberApplicationPublic)
async def update_member_application(
    application_id: str,
    body: ApplicationUpdateRequest,
    _manager: dict = Depends(get_applications_manager),
) -> MemberApplicationPublic:
    doc = await service.find_application(application_id)
    return await _with_member(await service.update(doc, body))


@router.delete("/{application_id}", status_code=204)
async def delete_member_application(application_id: str, _manager: dict = Depends(get_applications_manager)) -> None:
    await service.delete(await service.find_application(application_id))


@router.get("/{application_id}/resume")
async def download_member_resume(application_id: str, _manager: dict = Depends(get_applications_manager)) -> Response:
    return await service.resume_download(await service.find_application(application_id))


@router.put("/{application_id}/resume", response_model=MemberApplicationPublic)
async def replace_member_resume(
    application_id: str,
    resume: UploadFile = File(...),
    _manager: dict = Depends(get_applications_manager),
) -> MemberApplicationPublic:
    doc = await service.find_application(application_id)
    return await _with_member(await service.replace_resume(doc, resume))


@router.delete("/{application_id}/resume", response_model=MemberApplicationPublic)
async def remove_member_resume(
    application_id: str, _manager: dict = Depends(get_applications_manager)
) -> MemberApplicationPublic:
    doc = await service.find_application(application_id)
    return await _with_member(await service.remove_resume(doc))
