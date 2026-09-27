from datetime import datetime

from pydantic import BaseModel, Field


class AddJobBoardRequest(BaseModel):
    url: str = Field(min_length=4, max_length=500)


class JobBoardPublic(BaseModel):
    id: str
    platform: str
    company: str
    board_url: str
    added_at: datetime | None = None
    last_synced_at: datetime | None = None
    job_count: int


class AddJobBoardResponse(BaseModel):
    board: JobBoardPublic
    added_count: int
    skipped_duplicate_count: int
    filtered_out_count: int


class JobBoardListResponse(BaseModel):
    items: list[JobBoardPublic]


class SetPlatformCredentialRequest(BaseModel):
    api_key: str = Field(min_length=4, max_length=500)


class PlatformCredentialPublic(BaseModel):
    platform: str
    label: str
    has_key: bool
    updated_at: datetime | None = None
    signup_url: str = ""
    signup_note: str = ""


class PlatformCredentialListResponse(BaseModel):
    items: list[PlatformCredentialPublic]
