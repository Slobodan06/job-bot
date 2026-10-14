"""Generate a tailored cover letter from resume + job description."""
from __future__ import annotations

import base64
import json
import os
import re
from io import BytesIO
from pathlib import Path

from openai import AsyncOpenAI
from app.services.openai_compat import chat_completion_controls
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.services.pdf_fonts import register_reportlab_fira_fonts
from app.services.pdf_resume import extract_jd_target_role_title, sanitize_target_job_role
from app.services.pdf_text_util import sanitize_for_pdf
from app.services.sectionize import ParsedResume
from app.services.tailor import extract_keywords

_MARGIN_LR = 0.75 * inch
_MARGIN_TOP = 0.65 * inch
_MARGIN_BOTTOM = 0.65 * inch

_COVER_LETTER_SYSTEM = """You are an expert career writer. Write a professional, concise cover letter.

Rules:
- Use ONLY facts from the candidate's resume — never invent employers, degrees, or achievements.
- Match tone and keywords to the job description naturally (ATS-friendly).
- 3–4 short paragraphs: opening (interest + role fit), 1–2 body (relevant achievements with metrics when available), closing (call to action).
- Do NOT include markdown, bullet lists, or section headers.
- Return valid JSON: {"cover_letter": "..."}
- Include a proper salutation (Dear Hiring Manager, or Dear [Company] Team if company is known).
- End with a professional sign-off (Sincerely, / Best regards,) then the candidate's name on the next line.
- NEVER include an email address, phone number, street address, or any links anywhere in the letter (not in the header, body, or after the name).
- Keep total length 250–400 words.
"""


def _extract_candidate_name(contact: str) -> str:
    for line in (contact or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if "@" in stripped or re.search(r"https?://", stripped, re.I):
            continue
        if re.search(r"\+?\d[\d\s().\-]{7,}\d", stripped) and len(stripped) < 60:
            continue
        if "|" in stripped and len(stripped) < 120:
            continue
        if len(stripped.split()) <= 6 and not stripped.endswith("."):
            return stripped
    return ""


_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# 7+ digit phone numbers in common formats: +1 (555) 010-2000, 555.010.2000, +44 20 7946 0958
_PHONE_RE = re.compile(r"(?<![\w/])\+?\(?\d[\d\s().-]{6,}\d(?![\w/])")
_CONTACT_WORD = r"(?:e-?mail|phone|tel|telephone|mobile|cell)"


def strip_contact_details(text: str) -> str:
    """Remove email addresses and phone numbers from a cover letter.

    Lines that are only contact details (a signature block) are dropped; inline
    mentions are cut out and the leftover wording/punctuation tidied.
    """
    out: list[str] = []
    for line in (text or "").split("\n"):
        if not (_EMAIL_RE.search(line) or _PHONE_RE.search(line)):
            out.append(line)
            continue
        cleaned = _PHONE_RE.sub("", _EMAIL_RE.sub("", line))
        # Dangling labels ("Email:", "Phone |") and connectors ("reach me at .").
        cleaned = re.sub(rf"\b{_CONTACT_WORD}\s*[:.]?(?=\s*(?:[|·,;]|$))", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+(?:at|on|via)(?:\s+or)?\s*(?=[.,;!?]|$)", "", cleaned)
        cleaned = re.sub(r"\s+or\s*(?=[.,;!?]|$)", "", cleaned)
        cleaned = re.sub(r"\s*[|·,;]\s*(?=[|·,;.]|$)", "", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" |·,;-")
        if re.search(r"[A-Za-z]{3}", cleaned):
            out.append(cleaned)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _offline_cover_letter(
    parsed: ParsedResume,
    job_description: str,
    *,
    target_job_role: str,
    company_name: str,
    candidate_name: str,
) -> str:
    role = target_job_role or extract_jd_target_role_title(job_description) or "this role"
    company = company_name.strip() or "your organization"
    name = candidate_name or "Candidate"
    summary = (parsed.professional_summary or "").strip()
    summary_snip = summary[:280] + ("…" if len(summary) > 280 else "")
    salutation = f"Dear {company} Team," if company_name.strip() else "Dear Hiring Manager,"
    return (
        f"{salutation}\n\n"
        f"I am writing to express my strong interest in the {role} position at {company}. "
        f"{summary_snip}\n\n"
        f"My background aligns closely with your requirements. I would welcome the opportunity "
        f"to discuss how my experience can contribute to your team's goals.\n\n"
        f"Thank you for your time and consideration.\n\n"
        f"Sincerely,\n{name}"
    )


async def _llm_cover_letter(
    parsed: ParsedResume,
    job_description: str,
    api_key: str,
    *,
    target_job_role: str,
    company_name: str,
    candidate_name: str,
) -> str:
    keywords = extract_keywords(job_description, top_k=18)
    payload = {
        "candidate_name": candidate_name,
        "target_job_role": target_job_role,
        "company_name": company_name,
        "professional_summary": parsed.professional_summary,
        "professional_experience": parsed.professional_experience[:6000],
        "skills": parsed.skills[:3000],
        "education": parsed.education,
    }
    user_msg = (
        f"TARGET ROLE: {target_job_role}\n"
        f"COMPANY: {company_name or '(not specified — use generic salutation)'}\n"
        f"CANDIDATE NAME (sign-off): {candidate_name or '(not provided — end with the sign-off only)'}\n"
        f"JD KEYWORDS (weave naturally when truthful): {', '.join(keywords[:16])}\n\n"
        f"JOB DESCRIPTION:\n{job_description.strip()}\n\n"
        f"RESUME CONTEXT JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    client = AsyncOpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    completion = await client.chat.completions.create(
        model=model,
        **chat_completion_controls(model, max_output_tokens=1200, temperature=0.55),
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _COVER_LETTER_SYSTEM},
            {"role": "user", "content": user_msg},
        ],
    )
    raw = completion.choices[0].message.content or "{}"
    data = json.loads(raw)
    text = str(data.get("cover_letter", "")).strip()
    if not text or len(text) < 120:
        raise ValueError("empty cover letter")
    return text


def build_cover_letter_pdf(
    cover_letter: str,
    *,
    candidate_name: str = "",
) -> bytes:
    """Render cover letter as a clean letter-size PDF."""
    reg_font, _ = register_reportlab_fira_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=_MARGIN_LR,
        rightMargin=_MARGIN_LR,
        topMargin=_MARGIN_TOP,
        bottomMargin=_MARGIN_BOTTOM,
    )
    body_style = ParagraphStyle(
        "CoverBody",
        fontName=reg_font,
        fontSize=11,
        leading=15,
        alignment=TA_LEFT,
        spaceAfter=10,
    )
    header_style = ParagraphStyle(
        "CoverHeader",
        fontName=reg_font,
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=16,
    )

    story: list = []
    if candidate_name:  # name only — no email / phone on cover letters
        story.append(Paragraph(sanitize_for_pdf(candidate_name), header_style))
        story.append(Spacer(1, 0.15 * inch))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", (cover_letter or "").strip()) if p.strip()]
    if not paragraphs:
        paragraphs = [(cover_letter or "").strip()]
    for para in paragraphs:
        safe = sanitize_for_pdf(para).replace("\n", "<br/>")
        story.append(Paragraph(safe, body_style))

    doc.build(story)
    return buf.getvalue()


def cover_letter_download_filename(original_filename: str) -> str:
    stem = Path(original_filename).stem or "resume"
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip() or "resume"
    return f"{stem}-cover-letter.pdf"


async def generate_cover_letter(
    *,
    resume_model: object,
    job_description: str,
    original_filename: str = "resume.docx",
    target_job_role: str,
    company_name: str = "",
) -> dict:
    parsed = ParsedResume(
        contact=resume_model.contact_block(),
        professional_summary=resume_model.summary_text(),
        professional_experience=resume_model.experience_text(),
        skills=resume_model.skills_text(),
        education=resume_model.education_text(),
        other=resume_model.extras_text(),
    )
    role = sanitize_target_job_role(target_job_role) or extract_jd_target_role_title(job_description) or "this role"
    candidate_name = _extract_candidate_name(parsed.contact)

    key = os.getenv("OPENAI_API_KEY", "").strip()
    used_llm = False
    if key:
        try:
            cover_letter = await _llm_cover_letter(
                parsed,
                job_description,
                key,
                target_job_role=role,
                company_name=company_name.strip(),
                candidate_name=candidate_name,
            )
            used_llm = True
        except Exception:
            cover_letter = _offline_cover_letter(
                parsed,
                job_description,
                target_job_role=role,
                company_name=company_name.strip(),
                candidate_name=candidate_name,
            )
    else:
        cover_letter = _offline_cover_letter(
            parsed,
            job_description,
            target_job_role=role,
            company_name=company_name.strip(),
            candidate_name=candidate_name,
        )

    # Cover letters carry no contact details (no email / phone) — the name only.
    cover_letter = strip_contact_details(cover_letter)
    pdf_bytes = build_cover_letter_pdf(cover_letter, candidate_name=candidate_name)
    pdf_name = cover_letter_download_filename(original_filename)

    return {
        "cover_letter": cover_letter,
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "pdf_download_filename": pdf_name,
        "candidate_name": candidate_name,
        "target_job_role": role,
        "company_name": company_name.strip(),
        "used_llm": used_llm,
    }
