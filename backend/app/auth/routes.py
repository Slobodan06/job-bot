from datetime import UTC, datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user, get_owner_user, public_user
from app.auth.schemas import (
    AuthResponse,
    AuthResultResponse,
    ChangePasswordRequest,
    LoginRequest,
    MemberAccessUpdate,
    MessageResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    ResendVerificationRequest,
    UserPublic,
)
from app.auth.security import create_access_token, hash_password, verify_password
from app.auth.verification import new_verification_token, verification_is_valid
from app.auth.roles import owner_bootstrap_fields, user_can_build
from app.database import get_db, user_doc_to_public
from app.services.email import send_verification_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _auth_response(doc: dict) -> AuthResponse:
    token = create_access_token(str(doc["_id"]))
    return AuthResponse(
        access_token=token,
        user=UserPublic(**public_user(doc)),
    )


def _auth_result(doc: dict, *, message: str) -> AuthResultResponse:
    public = UserPublic(**public_user(doc))
    if not public.email_verified:
        return AuthResultResponse(
            status="pending_verification",
            message=message,
            email=public.email,
        )
    if not user_can_build(doc):
        token = create_access_token(str(doc["_id"]))
        return AuthResultResponse(
            status="pending_access",
            message="Your email is verified. Waiting for the owner to grant resume builder access.",
            email=public.email,
            access_token=token,
            user=public,
        )
    full = _auth_response(doc)
    return AuthResultResponse(
        status="authenticated",
        message=message,
        email=public.email,
        access_token=full.access_token,
        user=full.user,
    )


async def _issue_verification(doc: dict) -> None:
    token, expires = new_verification_token()
    db = get_db()
    await db.users.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "verification_token": token,
                "verification_token_expires": expires,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    await send_verification_email(doc["email"], token, name=doc.get("name") or "")


@router.post("/register", response_model=AuthResultResponse)
async def register(body: RegisterRequest) -> AuthResultResponse:
    db = get_db()
    email = body.email.strip().lower()
    existing = await db.users.find_one({"email": email})
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    now = datetime.now(UTC)
    bootstrap = owner_bootstrap_fields(email)
    doc = {
        "email": email,
        "password_hash": hash_password(body.password),
        "name": body.name,
        "avatar_url": "",
        "headline": "",
        "target_role": "",
        "location": "",
        "bio": "",
        "verification_token": None,
        "verification_token_expires": None,
        "created_at": now,
        "updated_at": now,
        **bootstrap,
    }
    result = await db.users.insert_one(doc)
    doc["_id"] = result.inserted_id

    if bootstrap["email_verified"]:
        return _auth_result(
            doc,
            message="Owner account created. You can use the resume builder and manage members.",
        )

    await _issue_verification(doc)
    return AuthResultResponse(
        status="pending_verification",
        message="Account created. Check your email for the activation link.",
        email=email,
    )


@router.post("/login", response_model=AuthResultResponse)
async def login(body: LoginRequest) -> AuthResultResponse:
    db = get_db()
    email = body.email.strip().lower()
    doc = await db.users.find_one({"email": email})
    if not doc or not doc.get("password_hash"):
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not verify_password(body.password, doc["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    public = user_doc_to_public(doc)
    if not public["email_verified"]:
        await _issue_verification(doc)
        return AuthResultResponse(
            status="pending_verification",
            message="We sent an activation link to your email. Please verify before continuing.",
            email=email,
        )

    return _auth_result(doc, message="Signed in successfully.")


@router.get("/verify-email", response_model=AuthResultResponse)
async def verify_email(token: str = Query(min_length=10)) -> AuthResultResponse:
    db = get_db()
    doc = await db.users.find_one({"verification_token": token})
    if not doc or not verification_is_valid(doc, token):
        raise HTTPException(status_code=400, detail="Invalid or expired activation link.")
    now = datetime.now(UTC)
    await db.users.update_one(
        {"_id": doc["_id"]},
        {
            "$set": {
                "email_verified": True,
                "updated_at": now,
            },
            "$unset": {
                "verification_token": "",
                "verification_token_expires": "",
            },
        },
    )
    doc = await db.users.find_one({"_id": doc["_id"]})
    return _auth_result(doc, message="Email verified successfully.")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(body: ResendVerificationRequest) -> MessageResponse:
    db = get_db()
    email = body.email.strip().lower()
    doc = await db.users.find_one({"email": email})
    if not doc:
        return MessageResponse(message="If an account exists, a new activation link was sent.")
    if user_doc_to_public(doc)["email_verified"]:
        return MessageResponse(message="This account is already verified. You can sign in.")
    await _issue_verification(doc)
    return MessageResponse(message="A new activation link was sent to your email.")


@router.get("/me", response_model=UserPublic)
async def me(user: dict = Depends(get_current_user)) -> UserPublic:
    return UserPublic(**public_user(user))


@router.patch("/profile", response_model=UserPublic)
async def update_profile(
    body: ProfileUpdateRequest,
    user: dict = Depends(get_current_user),
) -> UserPublic:
    db = get_db()
    updates: dict = {"updated_at": datetime.now(UTC)}
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        if value is None:
            continue
        if key == "name":
            stripped = value.strip()
            if not stripped:
                raise HTTPException(status_code=400, detail="Name cannot be empty.")
            updates[key] = stripped
        else:
            updates[key] = value.strip() if isinstance(value, str) else value
    if len(updates) <= 1:
        return UserPublic(**public_user(user))
    await db.users.update_one({"_id": user["_id"]}, {"$set": updates})
    doc = await db.users.find_one({"_id": user["_id"]})
    return UserPublic(**public_user(doc))


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
) -> MessageResponse:
    if not user.get("password_hash"):
        raise HTTPException(status_code=400, detail="Password change is not available.")
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    db = get_db()
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": hash_password(body.new_password),
                "updated_at": datetime.now(UTC),
            }
        },
    )
    return MessageResponse(message="Password updated successfully.")
