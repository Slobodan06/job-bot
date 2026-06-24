from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_owner_user, public_user
from app.auth.roles import user_is_owner
from app.auth.schemas import MemberAccessUpdate, MemberTemplateUpdate, UserPublic
from app.cv_templates.assignment import assign_cv_template
from app.database import get_db
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
        update_doc["$unset"] = {"cv_template_key": ""}
    await db.users.update_one({"_id": doc["_id"]}, update_doc)
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
