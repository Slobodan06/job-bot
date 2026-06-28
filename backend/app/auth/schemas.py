from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        return v.strip()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    headline: str | None = Field(default=None, max_length=200)
    target_role: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    bio: str | None = Field(default=None, max_length=2000)


class MemberAccessUpdate(BaseModel):
    has_access: bool


class MemberTemplateUpdate(BaseModel):
    template_key: str | None = Field(default=None, max_length=64)


class UserPublic(BaseModel):
    id: str
    email: str
    name: str = ""
    avatar_url: str = ""
    headline: str = ""
    target_role: str = ""
    location: str = ""
    bio: str = ""
    role: Literal["owner", "member"] = "member"
    email_verified: bool = False
    has_access: bool = False
    cv_template_key: str = ""
    cv_template_label: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


class AuthResultResponse(BaseModel):
    status: Literal["pending_access", "authenticated"]
    message: str
    email: str
    access_token: str | None = None
    user: UserPublic | None = None


class MessageResponse(BaseModel):
    message: str
