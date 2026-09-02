from pydantic import BaseModel, Field


class TailorResponse(BaseModel):
    tailored_resume: str = Field(..., description="Full tailored resume as assembled plain text.")
    tailored_contact: str = Field("", description="Tailored header/contact block including job-targeted title.")
    tailored_summary: str = Field("", description="Tailored professional summary section.")
    tailored_experience: str = Field("", description="Tailored professional experience section.")
    tailored_skills: str = Field(
        "",
        description="Tailored skills as labeled lines (e.g. Frontend: a, b / Database: x, y).",
    )
    tailored_education: str = Field("", description="Tailored education section.")
    tailored_other: str = Field("", description="Tailored certifications, projects, and other sections.")
    docx_base64: str = Field(
        "",
        description="Base64-encoded tailored .docx with in-place section updates on the uploaded template.",
    )
    download_filename: str = Field(
        "resume-tailored.docx",
        description="Suggested download name for the tailored Word file.",
    )
    pdf_base64: str = Field(
        "",
        description="Base64-encoded PDF converted from the tailored .docx (when conversion is available).",
    )
    pdf_download_filename: str = Field(
        "",
        description="Suggested download name for the tailored PDF file.",
    )
    keywords_highlighted: list[str] = Field(default_factory=list)
    experience_keywords_highlighted: list[str] = Field(
        default_factory=list,
        description="JD-critical terms bolded in experience bullets in the Word export.",
    )
    skills_keywords_highlighted: list[str] = Field(
        default_factory=list,
        description="Top JD-matched skill tokens bolded in the Skills section of the Word export.",
    )
    ats_tips: list[str] = Field(default_factory=list)
    used_llm: bool = Field(False, description="True if OpenAI was used for section rewriting.")
    openai_configured: bool = Field(
        False,
        description="True when OPENAI_API_KEY is set on the server that handled this request.",
    )
    llm_error: str = Field(
        "",
        description="When used_llm is false but openai_configured is true, a short sanitized failure reason.",
    )
    enable_bold_applied: bool = Field(
        True,
        description="True when JD keyword bolding was applied to the downloaded Word file.",
    )
    export_mode: str = Field(
        "fresh_pdf",
        description="fresh_pdf = new blank smart template; inplace_docx = edit uploaded Word file.",
    )
    template_key: str = Field("", description="Smart template key used for fresh PDF export.")
    template_label: str = Field("", description="Human-readable template name for fresh PDF export.")
    match_scores: dict[str, int] = Field(
        default_factory=dict,
        description="Separate resume match scores: keyword, evidence, minimum qualification, and credibility.",
    )
    gap_report: list[str] = Field(
        default_factory=list,
        description="Important job requirements that were not supported by verified candidate evidence.",
    )
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="Targeted questions to verify missing experience before adding it to the resume.",
    )
    integration_report: list[str] = Field(
        default_factory=list,
        description="How candidate-confirmed skills and experience were integrated or left unplaced.",
    )
    audit_report: dict = Field(
        default_factory=dict,
        description="Structured internal audit report with pipeline stages, bullet provenance, validation, and scoring.",
    )


class QualificationQuestion(BaseModel):
    id: str
    category: str
    title: str
    prompt: str
    why_it_matters: str
    detail_prompt: str
    suggested_details: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    confirmation_claim: str
    example_answer: str
    example_skills: str
    skills_prompt: str
    details_required_when_yes: bool = False


class QualificationAnalysisResponse(BaseModel):
    target_role: str = "Target role"
    intro: str
    questions: list[QualificationQuestion] = Field(default_factory=list)
    already_supported: list[str] = Field(default_factory=list)
    question_count: int = 0


class CoverLetterResponse(BaseModel):
    cover_letter: str = Field(..., description="Full cover letter plain text.")
    pdf_base64: str = Field("", description="Base64-encoded cover letter PDF.")
    pdf_download_filename: str = Field("cover-letter.pdf", description="Suggested PDF download name.")
    candidate_name: str = Field("", description="Candidate name extracted from resume contact.")
    target_job_role: str = Field("", description="Target role used in the letter.")
    company_name: str = Field("", description="Company name if provided.")
    used_llm: bool = Field(False, description="True if OpenAI generated the letter.")


class WorkExperienceRoleResponse(BaseModel):
    header: str = Field(..., description="Raw header line (title, company, location, dates).")
    company: str = Field("", description="Parsed company name when detectable.")
    title: str = Field("", description="Parsed job title when detectable.")
    location: str = Field("", description="Parsed location when detectable.")
    period: str = Field("", description="Parsed employment date range when detectable.")
    bullets: list[str] = Field(default_factory=list, description="Source bullet lines for this role.")
    bullet_count: int = Field(0, description="Number of bullet lines detected for this role.")


class ParseSectionsResponse(BaseModel):
    contact: str = Field("", description="Contact / header block.")
    professional_summary: str = Field("", description="Summary or profile section.")
    professional_experience: str = Field("", description="Full work experience section text.")
    skills: str = Field("", description="Skills section text.")
    education: str = Field("", description="Education section text.")
    other: str = Field("", description="Other sections (certifications, projects, etc.).")
    work_experience_roles: list[WorkExperienceRoleResponse] = Field(
        default_factory=list,
        description="Each detected work experience entry with header and bullets.",
    )
    role_count: int = Field(0, description="Total work experience roles detected.")
    experience_layout: str = Field(
        "paragraph",
        description="Word layout for experience: paragraph-based or table-based.",
    )
    sections_detected: list[str] = Field(
        default_factory=list,
        description="Section keys found in the resume (contact, professional_summary, etc.).",
    )
    source_format: str = Field(
        "docx",
        description="Input format used for parsing: docx, pdf, or doc.",
    )
    total_experience_bullets: int = Field(
        0,
        description="Total accomplishment bullets detected across all work-experience roles.",
    )
    resume_model: dict = Field(
        default_factory=dict,
        description="Normalized canonical resume model (contact, summary, skills, experience, education, extras, meta).",
    )
