"""Generate a clean, Unicode-safe PDF from tailored sections (ReportLab + embedded FiraGO)."""
from __future__ import annotations

import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.services.pdf_fonts import register_reportlab_fira_fonts
from app.services.pdf_text_util import sanitize_for_pdf

# Tight, contemporary page frame (letter = 8.5 × 11 in)
MODERN_MARGIN_LR = 0.48 * inch
MODERN_MARGIN_TOP = 0.42 * inch
MODERN_MARGIN_BOTTOM = 0.48 * inch
MODERN_CONTENT_WIDTH = 8.5 * inch - 2 * MODERN_MARGIN_LR


def _para_markup(text: str) -> str:
    t = sanitize_for_pdf(text or "")
    t = escape(t)
    t = re.sub(r"\r\n|\r|\n", "<br/>", t)
    return t


def build_tailored_resume_pdf(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    body_font, heading_font = register_reportlab_fira_fonts()
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        rightMargin=MODERN_MARGIN_LR,
        leftMargin=MODERN_MARGIN_LR,
        topMargin=MODERN_MARGIN_TOP,
        bottomMargin=MODERN_MARGIN_BOTTOM,
        title="Tailored resume",
    )
    base = getSampleStyleSheet()
    ink = colors.HexColor("#0f172a")
    muted = colors.HexColor("#64748b")
    heading = ParagraphStyle(
        "SecHeading",
        parent=base["Heading2"],
        fontName=heading_font,
        fontSize=8,
        leading=11,
        spaceBefore=10,
        spaceAfter=4,
        textColor=muted,
        alignment=TA_LEFT,
    )
    body = ParagraphStyle(
        "SecBody",
        parent=base["Normal"],
        fontName=body_font,
        fontSize=9.5,
        leading=13,
        alignment=TA_LEFT,
        textColor=ink,
        wordWrap="CJK",
    )
    contact_style = ParagraphStyle(
        "ContactLead",
        parent=body,
        fontName=heading_font,
        fontSize=15,
        leading=18,
        textColor=ink,
        spaceAfter=2,
    )
    contact_sub = ParagraphStyle(
        "ContactSub",
        parent=body,
        fontSize=9,
        leading=12,
        textColor=muted,
    )
    story: list = []

    def add_section(title: str, content: str) -> None:
        c = (content or "").strip()
        if not c:
            return
        story.append(Paragraph(_para_markup(title.upper()), heading))
        story.append(Paragraph(_para_markup(c), body))
        story.append(Spacer(1, 6))

    lead = sanitize_for_pdf(contact or "").strip()
    if lead:
        lines = lead.split("\n")
        story.append(Paragraph(_para_markup(lines[0]), contact_style))
        if len(lines) > 1:
            story.append(Paragraph(_para_markup("\n".join(lines[1:])), contact_sub))
        story.append(Spacer(1, 10))

    add_section("Summary", professional_summary)
    add_section("Experience", professional_experience)
    add_section("Skills", skills)
    add_section("Education", education)
    add_section("Additional", other)

    if len(story) == 0:
        story.append(Paragraph(_para_markup("(No content)"), body))

    doc.build(story)
    return buf.getvalue()
