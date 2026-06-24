from datetime import UTC, datetime

from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.services.template_catalog import get_template_meta


async def assign_cv_template(
    db,
    user_id: ObjectId,
    template_key: str | None,
    *,
    admin_override: bool = False,
) -> str:
    """Assign or clear a member's exclusive CV template. Returns the template label (or empty)."""
    now = datetime.now(UTC)
    if not template_key:
        await db.users.update_one(
            {"_id": user_id},
            {"$unset": {"cv_template_key": ""}, "$set": {"updated_at": now}},
        )
        return ""

    key = template_key.strip()
    try:
        meta = get_template_meta(key)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="Unknown CV template.") from e

    taken = await db.users.find_one({"cv_template_key": key, "_id": {"$ne": user_id}})
    if taken:
        if admin_override:
            await db.users.update_one(
                {"_id": taken["_id"]},
                {"$unset": {"cv_template_key": ""}, "$set": {"updated_at": now}},
            )
        else:
            raise HTTPException(
                status_code=409,
                detail="This CV template is already assigned to another member.",
            )

    try:
        await db.users.update_one(
            {"_id": user_id},
            {"$set": {"cv_template_key": key, "updated_at": now}},
        )
    except DuplicateKeyError as e:
        raise HTTPException(
            status_code=409,
            detail="This CV template was just assigned to another member.",
        ) from e

    return meta["label"]
