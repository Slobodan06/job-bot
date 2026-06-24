import secrets
from datetime import UTC, datetime, timedelta


def new_verification_token() -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=24)
    return token, expires


def verification_is_valid(doc: dict, token: str) -> bool:
    stored = doc.get("verification_token")
    expires = doc.get("verification_token_expires")
    if not stored or stored != token:
        return False
    if not expires:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return datetime.now(UTC) < expires
