"""Generate a tailored cover letter from resume + job description."""
from __future__ import annotations

import base64
import json
import os
import re
from io import BytesIO
from pathlib import Path

from openai import AsyncOpenAI
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.services.docx_resume import parse_resume_from_docx
from app.services.pdf_fonts import register_reportlab_fira_fonts
from app.services.pdf_resume import extract_jd_target_role_title, sanitize_target_job_role
from app.services.pdf_text_util import sanitize_for_pdf
from app.services.sectionize import ParsedResume
from app.services.tailor import extract_keywords, merge_profile_links_into_contact

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


def _extract_email(contact: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+\.\w+", contact or "")
    return match.group(0) if match else ""


def _extract_phone(contact: str) -> str:
    for line in (contact or "").splitlines():
        match = re.search(r"(\+?\d[\d\s().\-]{7,}\d)", line)
        if match:
            return match.group(1).strip()
    return ""


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
        "contact": parsed.contact,
        "professional_summary": parsed.professional_summary,
        "professional_experience": parsed.professional_experience[:6000],
        "skills": parsed.skills[:3000],
        "education": parsed.education,
    }
    user_msg = (
        f"TARGET ROLE: {target_job_role}\n"
        f"COMPANY: {company_name or '(not specified — use generic salutation)'}\n"
        f"CANDIDATE NAME (sign-off): {candidate_name or '(extract from contact)'}\n"
        f"JD KEYWORDS (weave naturally when truthful): {', '.join(keywords[:16])}\n\n"
        f"JOB DESCRIPTION:\n{job_description.strip()}\n\n"
        f"RESUME CONTEXT JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    client = AsyncOpenAI(api_key=api_key)
    completion = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.55,
        max_tokens=1200,
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
    email: str = "",
    phone: str = "",
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
    header_lines: list[str] = []
    if candidate_name:
        header_lines.append(candidate_name)
    if email:
        header_lines.append(email)
    if phone:
        header_lines.append(phone)
    if header_lines:
        story.append(Paragraph("<br/>".join(sanitize_for_pdf(line) for line in header_lines), header_style))
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
    source_docx_bytes: bytes,
    job_description: str,
    *,
    original_filename: str = "resume.docx",
    target_job_role: str,
    company_name: str = "",
) -> dict:
    docx_doc = parse_resume_from_docx(source_docx_bytes)
    parsed = docx_doc.parsed
    enriched_contact = merge_profile_links_into_contact(
        parsed.contact,
        docx_doc.plain_text,
        docx_bytes=source_docx_bytes,
    )
    parsed = ParsedResume(
        contact=enriched_contact,
        professional_summary=parsed.professional_summary,
        professional_experience=parsed.professional_experience,
        skills=parsed.skills,
        education=parsed.education,
        other=parsed.other,
    )
    role = sanitize_target_job_role(target_job_role)
    candidate_name = _extract_candidate_name(parsed.contact)
    email = _extract_email(parsed.contact)
    phone = _extract_phone(parsed.contact)

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

    pdf_bytes = build_cover_letter_pdf(
        cover_letter,
        candidate_name=candidate_name,
        email=email,
        phone=phone,
    )
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
