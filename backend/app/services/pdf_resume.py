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
    t = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", t)
    t = escape(t)
    return re.sub(r"\r\n|\r|\n", "<br/>", t)


_CONTACT_DETAIL_RE = re.compile(
    r"@|\+?\d[\d\s().-]{7,}|https?://|linkedin\.com|github\.com",
    re.I,
)


def _looks_like_contact_detail(line: str) -> bool:
    if _CONTACT_DETAIL_RE.search(line):
        return True
    if re.search(r",\s*[A-Za-z]", line) and not line.startswith("-"):
        return True
    return False


def parse_contact_header(contact: str) -> tuple[str, str | None, list[str]]:
    lines = [line.strip() for line in sanitize_for_pdf(contact or "").strip().split("\n") if line.strip()]
    if not lines:
        return "", None, []
    name = lines[0]
    rest = lines[1:]
    headline: str | None = None
    details: list[str] = []
    headline_parts: list[str] = []
    for line in rest:
        if "|" in line and (_looks_like_contact_detail(line) or "@" in line):
            details.extend(part.strip() for part in line.split("|") if part.strip())
            continue
        if _looks_like_contact_detail(line):
            details.append(line)
        else:
            headline_parts.append(line)
    if headline_parts:
        if len(headline_parts) == 1:
            headline = headline_parts[0]
        elif not details:
            if len(headline_parts) >= 2 and _looks_like_contact_detail(headline_parts[-1]):
                headline = headline_parts[0]
                details = headline_parts[1:]
            else:
                headline = " · ".join(headline_parts)
        else:
            headline = headline_parts[0]
            if len(headline_parts) > 1:
                details = headline_parts[1:] + details
    return name, headline, details


def format_contact_header_markup(
    contact: str,
    *,
    name_size: int = 14,
    name_color: str | None = None,
    headline_color: str = "#475569",
    detail_color: str = "#64748b",
) -> str:
    name, headline, details = parse_contact_header(contact)
    if not name:
        return ""
    name_attr = f" color='{name_color}'" if name_color else ""
    parts = [f"<b><font size='{name_size}'{name_attr}>{escape(name)}</font></b>"]
    if headline:
        parts.append(
            f"<br/><font color='{headline_color}' size='9'>{escape(headline)}</font>"
        )
    if details:
        joined = " · ".join(escape(item) for item in details)
        parts.append(f"<br/><font color='{detail_color}' size='9'>{joined}</font>")
    return "".join(parts)


_BULLET_RE = re.compile(r"^[-•*–—]\s*")


def _strip_trailing_breaks(html: str) -> str:
    """Remove trailing <br/> tags without corrupting closing tags like </font>."""
    while html.endswith("<br/>"):
        html = html[:-5]
    return html


def format_experience_markup(content: str) -> str:
    text = sanitize_for_pdf(content or "").strip()
    if not text:
        return ""
    text = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text)
    if re.search(r"\n\s*\n", text):
        raw_blocks = re.split(r"\n\s*\n", text)
        line_blocks: list[list[str]] = []
        for block in raw_blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            if lines:
                line_blocks.append(lines)
    else:
        line_blocks = _split_experience_lines(text)

    html_parts: list[str] = []
    for lines in line_blocks:
        headers: list[str] = []
        bullets: list[str] = []
        for line in lines:
            if _BULLET_RE.match(line):
                bullets.append(_BULLET_RE.sub("", line).strip())
            elif bullets:
                bullets[-1] = f"{bullets[-1]} {line}"
            else:
                headers.append(line)
        if headers:
            html_parts.append(
                f"<b><font size='10' color='#0f172a'>{escape(headers[0])}</font></b><br/>"
            )
            if len(headers) > 1:
                html_parts.append(
                    f"<font color='#334155'><b>{escape(headers[1])}</b></font><br/>"
                )
            meta = [escape(item) for item in headers[2:]]
            if meta:
                html_parts.append(
                    f"<font color='#64748b' size='8'>{' · '.join(meta)}</font><br/>"
                )
            if bullets:
                html_parts.append("<br/>")
        for bullet in bullets:
            html_parts.append(
                f"<font color='#0f172a' size='9'>• {escape(bullet)}</font><br/>"
            )
        html_parts.append("<br/>")
    return _strip_trailing_breaks("".join(html_parts))


def _split_experience_lines(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    blocks: list[list[str]] = []
    current: list[str] = []
    seen_bullets = False
    for line in lines:
        is_bullet = bool(_BULLET_RE.match(line))
        if not is_bullet and seen_bullets and current:
            blocks.append(current)
            current = []
            seen_bullets = False
        current.append(line)
        if is_bullet:
            seen_bullets = True
    if current:
        blocks.append(current)
    return blocks


def _section_body_markup(title: str, content: str) -> str:
    if "experience" in title.lower():
        return format_experience_markup(content)
    return _para_markup(content)


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
    story: list = []

    lead = sanitize_for_pdf(contact or "").strip()
    if lead:
        story.append(Paragraph(format_contact_header_markup(lead, name_size=15), contact_style))
        story.append(Spacer(1, 10))

    def add_section(title: str, content: str) -> None:
        c = (content or "").strip()
        if not c:
            return
        story.append(Paragraph(_para_markup(title.upper()), heading))
        story.append(Paragraph(_section_body_markup(title, c), body))
        story.append(Spacer(1, 6))

    add_section("Summary", professional_summary)
    add_section("Experience", professional_experience)
    add_section("Skills", skills)
    add_section("Education", education)
    add_section("Additional", other)

    if len(story) == 0:
        story.append(Paragraph(_para_markup("(No content)"), body))

    doc.build(story)
    return buf.getvalue()
