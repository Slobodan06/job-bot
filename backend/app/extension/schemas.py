from typing import Any

from pydantic import BaseModel, Field


class DetectedJob(BaseModel):
    url: str = Field(default="", max_length=2000)
    text: str = Field(default="", max_length=40000)
    page_title: str = Field(default="", max_length=500)
    company: str = Field(default="", max_length=200)
    job_title: str = Field(default="", max_length=300)
    location: str = Field(default="", max_length=200)
    ats: str = Field(default="", max_length=32)


class AnalyzeJobResponse(BaseModel):
    company: str = ""
    job_title: str = ""
    location: str = ""
    seniority: str = ""
    keywords: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)


class CustomAnswer(BaseModel):
    q: str = Field(max_length=300)
    a: str = Field(max_length=2000)


class AutofillProfile(BaseModel):
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    phone_country_code: str = ""
    phone_device_type: str = ""
    address: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    website: str = ""
    pronouns: str = ""
    work_authorized: bool | None = None
    requires_sponsorship: bool | None = None
    currently_employed: bool | None = None
    willing_to_relocate: bool | None = None
    over_18: bool | None = None
    worked_here_before: bool | None = None
    has_drivers_license: bool | None = None
    desired_salary: str = ""
    notice_period_days: str = ""
    start_date: str = ""
    years_of_experience: str = ""
    highest_education: str = ""
    how_heard_about_us: str = ""
    gender: str = ""
    race_ethnicity: str = ""
    veteran_status: str = ""
    disability_status: str = ""
    # Write-only: a throwaway password for ATS's that require account creation
    # to apply (Workday, notably). Encrypted at rest; never returned by GET
    # /api/extension/profile (see ExtensionProfileResponse.has_application_password).
    application_password: str = Field(default="", max_length=200)
    custom_answers: list[CustomAnswer] = Field(default_factory=list)


class ExtensionProfileResponse(BaseModel):
    name: str = ""
    email: str = ""
    has_base_resume: bool = False
    autofill_profile: dict[str, Any] = Field(default_factory=dict)


class FormField(BaseModel):
    key: str = Field(max_length=120)
    label: str = Field(default="", max_length=500)
    name: str = Field(default="", max_length=200)
    id: str = Field(default="", max_length=200)
    type: str = Field(default="text", max_length=32)
    placeholder: str = Field(default="", max_length=300)
    autocomplete: str = Field(default="", max_length=64)
    aria_label: str = Field(default="", max_length=300)
    required: bool = False
    options: list[str] = Field(default_factory=list)
    # Set when the field lives inside a repeated block the page itself numbers
    # ("Work Experience 1", "Work Experience 2", "Education 1", ...) — Workday
    # and several other ATS's ask Company/Title/Location/From/To/Description
    # once per employer rather than a single "current employer" question.
    group_kind: str = Field(default="", max_length=16)  # "experience" | "education" | ""
    group_index: int | None = Field(default=None, ge=0)


class AutofillRequest(BaseModel):
    job: DetectedJob
    fields: list[FormField] = Field(default_factory=list, max_length=200)
    variant: str = Field(default="quick", pattern="^(quick|tailored)$")
    resume_variant_id: str | None = None


class AutofillValue(BaseModel):
    value: str
    source: str
    confidence: float = 0.0
    canonical: str = ""


class ResumeAttachment(BaseModel):
    variant_id: str
    filename: str
    download_path: str
    kind: str = "pdf"


class AutofillResponse(BaseModel):
    values: dict[str, AutofillValue] = Field(default_factory=dict)
    answers: dict[str, str] = Field(default_factory=dict)
    resume: ResumeAttachment | None = None
    application_id: str | None = None
    unfilled: list[str] = Field(default_factory=list)


class TailorForJobRequest(BaseModel):
    job: DetectedJob
    target_job_role: str = Field(default="", max_length=200)


class TailorForJobResponse(BaseModel):
    resume: ResumeAttachment
    docx_variant_id: str
    match_scores: dict[str, int] = Field(default_factory=dict)
    application_id: str | None = None
