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
    notes: str = Field(default="", max_length=4000)
    submitted_at: datetime | None = None


class ApplicationUpdateRequest(BaseModel):
    job_url: str | None = Field(default=None, min_length=1, max_length=2000)
    company: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=300)
    location: str | None = Field(default=None, max_length=200)
    status: str | None = Field(default=None, max_length=32)
    notes: str | None = Field(default=None, max_length=4000)
    submitted_at: datetime | None = None


class AppliedResumePublic(BaseModel):
    file_id: str
    filename: str
    content_type: str
    size: int = 0
    source: str
    stored_at: datetime | None = None


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
    applied_resume: AppliedResumePublic | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    submitted_at: datetime | None = None


class ApplicationListResponse(BaseModel):
    items: list[ApplicationPublic]
    next_cursor: str | None = None


class ApplicationStatsResponse(BaseModel):
    total: int
    by_status: dict[str, int]


class MemberRef(BaseModel):
    id: str
    name: str = ""
    email: str = ""


class MemberApplicationPublic(ApplicationPublic):
    """An application as the manager sees it: with the member it belongs to."""

    member: MemberRef


class MemberApplicationListResponse(BaseModel):
    items: list[MemberApplicationPublic]
    next_cursor: str | None = None


class MemberTrackingSummary(BaseModel):
    member: MemberRef
    role: str = "member"
    member_type: str = "team_member"
    has_access: bool = False
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    last_applied_at: datetime | None = None
    last_activity_at: datetime | None = None


class DailyMemberCount(BaseModel):
    id: str
    name: str
    count: int


class DailyPoint(BaseModel):
    date: str  # YYYY-MM-DD in the requested time zone
    count: int
    members: list[DailyMemberCount] = Field(default_factory=list)


class DailyApplicationsResponse(BaseModel):
    days: list[DailyPoint]
    total: int
    tz: str


class EmailSignal(BaseModel):
    """One Gmail message the extension saw (inbox row or opened message)."""

    key: str = Field(min_length=1, max_length=200)
    from_name: str = Field(default="", max_length=200)
    from_email: str = Field(default="", max_length=200)
    subject: str = Field(default="", max_length=500)
    snippet: str = Field(default="", max_length=1000)
    body: str = Field(default="", max_length=8000)
    received_at: datetime | None = None


class EmailSignalsRequest(BaseModel):
    emails: list[EmailSignal] = Field(max_length=40)


class EmailStatusUpdate(BaseModel):
    application_id: str
    company: str = ""
    job_title: str = ""
    previous_status: str
    status: str
    subject: str = ""


class EmailSignalsResponse(BaseModel):
    processed_keys: list[str]
    updated: list[EmailStatusUpdate]
