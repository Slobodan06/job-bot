from pydantic import BaseModel, Field


class TailorResponse(BaseModel):
    tailored_resume: str = Field(..., description="Full tailored resume as assembled plain text.")
    tailored_summary: str = Field("", description="Tailored professional summary section.")
    tailored_experience: str = Field("", description="Tailored professional experience section.")
    tailored_skills: str = Field(
        "",
        description="Tailored skills as labeled lines (e.g. Frontend: a, b / Database: x, y).",
    )
    pdf_base64: str = Field(
        "",
        description="Base64-encoded PDF of the tailored resume (empty if generation failed).",
    )
    download_filename: str = Field(
        "resume.pdf",
        description="Suggested download name (same stem as upload, .pdf extension).",
    )
    keywords_highlighted: list[str] = Field(default_factory=list)
    ats_tips: list[str] = Field(default_factory=list)
    used_llm: bool = Field(False, description="True if OpenAI was used for section rewriting.")
    pdf_template_key: str = Field(
        "",
        description="Layout id for the generated PDF (e.g. two-column); empty if PDF failed.",
    )
    pdf_template_label: str = Field(
        "",
        description="Human-readable layout name shown in the UI.",
    )
