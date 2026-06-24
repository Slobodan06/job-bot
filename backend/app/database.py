import os
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.auth.roles import get_owner_email, is_owner_email
from app.services.template_catalog import get_template_meta

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_mongodb_uri() -> str:
    uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        user = os.getenv("MONGODB_USERNAME", "").strip()
        password = os.getenv("MONGODB_PASSWORD", "").strip()
        if user and password:
            uri = f"mongodb+srv://{user}:{password}@cluster0.tnzlya6.mongodb.net"
    if not uri:
        raise RuntimeError(
            "MongoDB is not configured. Set MONGODB_URI or MONGODB_USERNAME/MONGODB_PASSWORD."
        )
    db_name = os.getenv("MONGODB_DB_NAME", "jobbot").strip() or "jobbot"
    if "?" in uri:
        base, query = uri.split("?", 1)
        if not base.rstrip("/").split("/")[-1] or base.endswith(".mongodb.net"):
            uri = f"{base.rstrip('/')}/{db_name}?{query}"
    elif not uri.rstrip("/").split("/")[-1] or uri.endswith(".mongodb.net"):
        uri = f"{uri.rstrip('/')}/{db_name}"
    return uri


async def connect_db() -> None:
    global _client, _db
    if _client is not None:
        return
    uri = get_mongodb_uri()
    _client = AsyncIOMotorClient(uri)
    _db = _client.get_default_database()


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None


def get_db() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database is not connected.")
    return _db


async def ensure_indexes() -> None:
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.users.create_index("verification_token", sparse=True)
    await db.users.create_index("cv_template_key", unique=True, sparse=True)

    owner_email = get_owner_email()
    if owner_email:
        await db.users.update_one(
            {"email": owner_email},
            {
                "$set": {
                    "role": "owner",
                    "email_verified": True,
                    "has_access": True,
                }
            },
        )


def user_doc_to_public(doc: dict[str, Any]) -> dict[str, Any]:
    email = doc.get("email") or ""
    role = doc.get("role") or ("owner" if is_owner_email(email) else "member")
    email_verified = bool(doc.get("email_verified")) or is_owner_email(email)
    has_access = bool(doc.get("has_access")) or role == "owner"
    cv_template_key = doc.get("cv_template_key") or ""
    cv_template_label = ""
    if cv_template_key:
        try:
            meta = get_template_meta(cv_template_key)
            cv_template_label = meta["label"]
        except KeyError:
            cv_template_label = cv_template_key
    return {
        "id": str(doc["_id"]),
        "email": email,
        "name": doc.get("name") or "",
        "avatar_url": doc.get("avatar_url") or "",
        "headline": doc.get("headline") or "",
        "target_role": doc.get("target_role") or "",
        "location": doc.get("location") or "",
        "bio": doc.get("bio") or "",
        "role": role,
        "email_verified": email_verified,
        "has_access": has_access,
        "cv_template_key": cv_template_key,
        "cv_template_label": cv_template_label,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }
