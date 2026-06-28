from bson import ObjectId
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.roles import user_can_build, user_is_owner
from app.auth.security import decode_access_token
from app.database import get_db, user_doc_to_public

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Not authenticated.")
    try:
        payload = decode_access_token(creds.credentials)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    user_id = payload.get("sub")
    if not user_id or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=401, detail="Invalid token subject.")
    db = get_db()
    doc = await db.users.find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(status_code=401, detail="User not found.")
    return doc


async def get_verified_user(user: dict = Depends(get_current_user)) -> dict:
    public = user_doc_to_public(user)
    if not public["email_verified"]:
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Check your inbox for the activation link.",
        )
    return user


async def get_builder_user(user: dict = Depends(get_verified_user)) -> dict:
    if not user_can_build(user):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to the resume builder yet. Contact the site owner.",
        )
    return user


async def get_owner_user(user: dict = Depends(get_current_user)) -> dict:
    if not user_is_owner(user):
        raise HTTPException(status_code=403, detail="Owner access required.")
    return user


def public_user(doc: dict) -> dict:
    return user_doc_to_public(doc)
