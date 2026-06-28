import os


def get_owner_email() -> str:
    return os.getenv("OWNER_EMAIL", "").strip().lower()


def is_owner_email(email: str) -> bool:
    owner = get_owner_email()
    return bool(owner) and email.strip().lower() == owner


def owner_bootstrap_fields(email: str) -> dict:
    if is_owner_email(email):
        return {
            "role": "owner",
            "email_verified": True,
            "has_access": True,
        }
    return {
        "role": "member",
        "email_verified": True,
        "has_access": False,
    }


def user_can_build(doc: dict) -> bool:
    if doc.get("role") == "owner":
        return True
    return bool(doc.get("has_access"))


def user_is_owner(doc: dict) -> bool:
    return doc.get("role") == "owner" or is_owner_email(doc.get("email", ""))
