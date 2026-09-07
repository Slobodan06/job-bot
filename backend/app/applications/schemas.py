from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ApplicationUpsertRequest(BaseModel):
    job_url: str = Field(min_length=1, max_length=2000)
    ats: str = Field(default="", max_length=32)
    company: str = Field(default="", max_length=200)
    job_title: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    jd_text: str = Field(default="", max_length=40000)
    status: str = Field(default="detected", max_length=32)


class ApplicationUpdateRequest(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=4000)


class ApplicationPublic(BaseModel):
    id: str
    job_url: str
    ats: str
    company: str
    job_title: str
    location: str
    status: str
    resume_variant_id: str | None = None
    notes: str = ""
    answers: list[dict[str, Any]] = Field(default_factory=list)
    scores: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    submitted_at: datetime | None = None


class ApplicationListResponse(BaseModel):
    items: list[ApplicationPublic]
    next_cursor: str | None = None


class ApplicationStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]
