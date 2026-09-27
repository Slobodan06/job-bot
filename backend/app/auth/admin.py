from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_owner_user, public_user
from app.auth.roles import user_is_owner
from app.auth.schemas import (
    MemberDeleteResponse,
    MemberAccessUpdate,
    MemberPermissionsUpdate,
    MemberTemplateUpdate,
    MemberTypeUpdate,
    UserPublic,
)
from app.cv_templates.assignment import assign_cv_template
from app.database import get_db
from app.resume.store import delete_all_user_files
from app.services.template_catalog import list_template_catalog

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/templates", response_model=list[dict[str, str]])
async def list_all_templates(_owner: dict = Depends(get_owner_user)) -> list[dict[str, str]]:
    return list_template_catalog()


@router.get("/members", response_model=list[UserPublic])
async def list_members(_owner: dict = Depends(get_owner_user)) -> list[UserPublic]:
    db = get_db()
    cursor = db.users.find({}).sort("created_at", -1)
    members: list[UserPublic] = []
    async for doc in cursor:
        members.append(UserPublic(**public_user(doc)))
    return members


@router.patch("/members/{member_id}/access", response_model=UserPublic)
async def update_member_access(
    member_id: str,
    body: MemberAccessUpdate,
    owner: dict = Depends(get_owner_user),
) -> UserPublic:
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member id.")
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(member_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Member not found.")
    if user_is_owner(doc):
        raise HTTPException(status_code=400, detail="Cannot change access for the owner account.")
    update_doc: dict = {
        "$set": {
            "has_access": body.has_access,
            "updated_at": datetime.now(UTC),
        }
    }
    if not body.has_access:
        # Losing builder access also drops delegated permissions.
        update_doc["$unset"] = {"cv_template_key": "", "can_manage_applications": ""}
    await db.users.update_one({"_id": doc["_id"]}, update_doc)
    updated = await db.users.find_one({"_id": doc["_id"]})
    return UserPublic(**public_user(updated))


@router.patch("/members/{member_id}/permissions", response_model=UserPublic)
async def update_member_permissions(
    member_id: str,
    body: MemberPermissionsUpdate,
    owner: dict = Depends(get_owner_user),
) -> UserPublic:
    """Owner grants/revokes a member's right to manage everyone's tracked applications."""
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member id.")
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(member_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Member not found.")
    if user_is_owner(doc):
        raise HTTPException(status_code=400, detail="The owner always has every permission.")
    if body.can_manage_applications and not doc.get("has_access"):
        raise HTTPException(status_code=400, detail="Grant builder access first.")
    await db.users.update_one(
        {"_id": doc["_id"]},
        {"$set": {"can_manage_applications": body.can_manage_applications, "updated_at": datetime.now(UTC)}},
    )
    updated = await db.users.find_one({"_id": doc["_id"]})
    return UserPublic(**public_user(updated))


@router.patch("/members/{member_id}/type", response_model=UserPublic)
async def update_member_type(
    member_id: str,
    body: MemberTypeUpdate,
    owner: dict = Depends(get_owner_user),
) -> UserPublic:
    """Owner marks a member as a team member or a bidder.

    Members with the "Team tracker" permission only see bidders' applications.
    """
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member id.")
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(member_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Member not found.")
    if user_is_owner(doc):
        raise HTTPException(status_code=400, detail="The owner account has no member type.")
    await db.users.update_one(
        {"_id": doc["_id"]},
        {"$set": {"member_type": body.member_type, "updated_at": datetime.now(UTC)}},
    )
    updated = await db.users.find_one({"_id": doc["_id"]})
    return UserPublic(**public_user(updated))


@router.patch("/members/{member_id}/template", response_model=UserPublic)
async def update_member_template(
    member_id: str,
    body: MemberTemplateUpdate,
    owner: dict = Depends(get_owner_user),
) -> UserPublic:
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member id.")
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(member_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Member not found.")
    if user_is_owner(doc):
        raise HTTPException(status_code=400, detail="Cannot change template for the owner account.")

    key = body.template_key.strip() if body.template_key else None
    if key == "":
        key = None

    await assign_cv_template(db, doc["_id"], key, admin_override=True)
    updated = await db.users.find_one({"_id": doc["_id"]})
    return UserPublic(**public_user(updated))


@router.delete("/members/{member_id}", response_model=MemberDeleteResponse)
async def delete_member(member_id: str, owner: dict = Depends(get_owner_user)) -> MemberDeleteResponse:
    """Permanently remove a member and everything that belongs to them.

    Deletes the account (profile, saved base resume, autofill profile, CV template
    assignment — the template becomes free for someone else), their tracked
    applications, and all their stored resume files. Shared data (job boards,
    sourced jobs) is untouched. Their existing sessions stop working immediately.
    """
    if not ObjectId.is_valid(member_id):
        raise HTTPException(status_code=400, detail="Invalid member id.")
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(member_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Member not found.")
    if user_is_owner(doc) or doc["_id"] == owner["_id"]:
        raise HTTPException(status_code=400, detail="The owner account can't be removed.")

    files_deleted = await delete_all_user_files(doc["_id"])
    apps = await db.applications.delete_many({"user_id": doc["_id"]})
    await db.users.delete_one({"_id": doc["_id"]})
    return MemberDeleteResponse(
        email=doc.get("email") or "",
        applications_deleted=apps.deleted_count,
        files_deleted=files_deleted,
    )
