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
    ats_tips: list[str] = Field(default_factory=list)
    used_llm: bool = Field(False, description="True if OpenAI was used for section rewriting.")
    enable_bold_applied: bool = Field(
        True,
        description="True when JD keyword bolding was applied to the downloaded Word file.",
    )
