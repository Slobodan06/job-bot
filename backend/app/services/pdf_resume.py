"""Generate a clean, Unicode-safe PDF from tailored sections (ReportLab + embedded FiraGO)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
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

_URL_IN_TEXT_RE = re.compile(
    r"https?://[^\s<>\"']+|"
    r"(?:https?://)?(?:www\.)?linkedin\.com[/\w\-?=&%#.+]*|"
    r"(?:https?://)?(?:www\.)?github\.com[/\w\-?=&%#.+]*|"
    r"(?:https?://)?(?:www\.)?[a-z0-9][a-z0-9\-]*\.(?:dev|io|me|tech|app|com|net|org)[/\w\-?=&%#.+]*",
    re.I,
)
_EMAIL_LINE_RE = re.compile(r"^[^@\s/]+@[^@\s]+\.[^@\s]+$")
_LINK_LABELS = frozenset(
    {"portfolio", "linkedin", "github", "website", "blog", "linktree", "personal website", "link"}
)


def _para_markup(text: str) -> str:
    t = sanitize_for_pdf(text or "")
    t = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", t)
    t = escape(t)
    return re.sub(r"\r\n|\r|\n", "<br/>", t)


def _normalize_url(url: str) -> str:
    u = (url or "").strip().rstrip(".,;)")
    if not u:
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u.lstrip("/")
    return u


def _extract_url(text: str) -> str | None:
    stripped = (text or "").strip()
    if _EMAIL_LINE_RE.match(stripped):
        return None
    match = _URL_IN_TEXT_RE.search(stripped)
    if not match:
        return None
    url = match.group(0)
    if "@" in url.split("/")[0]:
        return None
    return _normalize_url(url)


def _href_markup(label: str, url: str, color: str = "#0d9488") -> str:
    return f'<a href="{escape(_normalize_url(url))}" color="{color}">{escape(label)}</a>'


@dataclass
class ParsedContact:
    name: str
    headline: str | None
    linkedin_url: str | None
    links: list[tuple[str, str]] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


_CONTACT_DETAIL_RE = re.compile(
    r"@|\+?\d[\d\s().-]{7,}|https?://|linkedin\.com|github\.com",
    re.I,
)


def _looks_like_contact_detail(line: str) -> bool:
    if _extract_url(line):
        return True
    if _CONTACT_DETAIL_RE.search(line):
        return True
    if re.search(r",\s*[A-Za-z]", line) and not line.startswith("-"):
        return True
    return False


def _is_link_label_line(line: str) -> bool:
    label = line.strip().lower().rstrip(": ")
    return label in _LINK_LABELS


def _link_label_for(line: str, url: str) -> str:
    text = f"{line} {url}".lower()
    if "linkedin" in text:
        return "LinkedIn"
    if "github" in text:
        return "GitHub"
    if "portfolio" in text or "behance" in text or "dribbble" in text:
        return "Portfolio"
    if "website" in line.lower() or "blog" in line.lower():
        return line.strip().rstrip(": ").title() or "Website"
    return "Portfolio"


def _split_name_and_title(line: str) -> tuple[str, str | None]:
    """Split a combined 'First Last Job Title' line from PDF extraction."""
    s = line.strip()
    if not s or _looks_like_contact_detail(s) or _is_link_label_line(s):
        return s, None
    words = s.split()
    if len(words) <= 2:
        return s, None
    if not (words[0][0].isupper() and words[1][0].isupper()):
        return s, None
    title_words = words[2:]
    title = " ".join(title_words).strip()
    if not title or _looks_like_contact_detail(title):
        return s, None
    return " ".join(words[:2]), title


def _register_link(parsed: ParsedContact, label: str, url: str) -> None:
    url = _normalize_url(url)
    if not url:
        return
    key = url.lower().rstrip("/")
    if any(existing.lower().rstrip("/") == key for _, existing in parsed.links):
        return
    if label.lower() == "linkedin" or "linkedin.com" in key:
        parsed.linkedin_url = parsed.linkedin_url or url
        if label.lower() == "linkedin":
            parsed.links.append(("LinkedIn", url))
        return
    parsed.links.append((label, url))


def parse_contact(contact: str) -> ParsedContact:
    lines = [line.strip() for line in sanitize_for_pdf(contact or "").strip().split("\n") if line.strip()]
    if not lines:
        return ParsedContact("", None, None)
    name, title_from_name = _split_name_and_title(lines[0])
    parsed = ParsedContact(name=name, headline=title_from_name, linkedin_url=None)
    headline_parts: list[str] = []
    i = 1
    while i < len(lines):
        line = lines[i]
        url = _extract_url(line)

        if url:
            label = _link_label_for(line, url)
            _register_link(parsed, label, url)
            i += 1
            continue

        if _is_link_label_line(line):
            label = line.strip().rstrip(": ").title()
            if i + 1 < len(lines):
                next_url = _extract_url(lines[i + 1])
                if next_url:
                    _register_link(parsed, label, next_url)
                    i += 2
                    continue
            i += 1
            continue

        if _EMAIL_LINE_RE.match(line.strip()):
            parsed.details.append(line.strip())
            i += 1
            continue

        if "|" in line:
            for part in line.split("|"):
                part = part.strip()
                if part:
                    part_url = _extract_url(part)
                    if part_url:
                        _register_link(parsed, _link_label_for(part, part_url), part_url)
                    elif _looks_like_contact_detail(part):
                        parsed.details.append(part)
            i += 1
            continue

        if _looks_like_contact_detail(line):
            parsed.details.append(line)
            i += 1
            continue

        headline_parts.append(line)
        i += 1

    if headline_parts:
        if parsed.headline is None:
            if len(headline_parts) == 1:
                parsed.headline = headline_parts[0]
            elif not parsed.details:
                parsed.headline = headline_parts[0]
                parsed.details.extend(headline_parts[1:])
            else:
                parsed.headline = " · ".join(headline_parts)
        else:
            extra = " · ".join(headline_parts)
            parsed.headline = f"{parsed.headline} · {extra}" if extra else parsed.headline
    return parsed


def parse_contact_header(contact: str) -> tuple[str, str | None, list[str]]:
    """Backward-compatible tuple API."""
    parsed = parse_contact(contact)
    details = list(parsed.details)
    for label, url in parsed.links:
        if parsed.linkedin_url and url == parsed.linkedin_url:
            continue
        details.append(f"{label}: {url}")
    return parsed.name, parsed.headline, details


def format_contact_name_markup(
    parsed: ParsedContact,
    *,
    name_color: str | None = None,
    link_color: str | None = None,
) -> str:
    if not parsed.name:
        return ""
    color = link_color or name_color or "#0f172a"
    if parsed.linkedin_url:
        return (
            f'<a href="{escape(_normalize_url(parsed.linkedin_url))}" color="{color}">'
            f"<b>{escape(parsed.name)}</b></a>"
        )
    return f"<b>{escape(parsed.name)}</b>"


def format_contact_details_markup(
    parsed: ParsedContact,
    *,
    detail_color: str = "#64748b",
    link_color: str = "#0d9488",
) -> str:
    parts: list[str] = []
    for item in parsed.details:
        parts.append(f'<font color="{detail_color}">{escape(item)}</font>')
    for label, url in parsed.links:
        if parsed.linkedin_url and url == parsed.linkedin_url:
            continue
        parts.append(_href_markup(label, url, link_color))
    return " · ".join(parts)


def format_contact_header_markup(
    contact: str,
    *,
    name_size: int = 14,
    name_color: str | None = None,
    headline_color: str = "#475569",
    detail_color: str = "#64748b",
    link_color: str = "#0d9488",
    detail_size: int = 9,
) -> str:
    parsed = parse_contact(contact)
    if not parsed.name:
        return ""
    name_attr = f" color='{name_color}'" if name_color else ""
    link_attr = f" color='{link_color or name_color or '#0d9488'}'" if (link_color or name_color) else ""
    if parsed.linkedin_url:
        name_html = (
            f"<a href='{escape(_normalize_url(parsed.linkedin_url))}'{link_attr}>"
            f"<b><font size='{name_size}'{name_attr}>{escape(parsed.name)}</font></b></a>"
        )
    else:
        name_html = f"<b><font size='{name_size}'{name_attr}>{escape(parsed.name)}</font></b>"
    parts = [name_html]
    if parsed.headline:
        parts.append(
            f"<br/><font color='{headline_color}' size='{detail_size + 1}'>{escape(parsed.headline)}</font>"
        )
    detail_html = format_contact_details_markup(
        parsed, detail_color=detail_color, link_color=link_color or "#0d9488"
    )
    if detail_html:
        parts.append(f"<br/><font size='{detail_size}'>{detail_html}</font>")
    return "".join(parts)


def merge_profile_links_into_contact(contact: str, full_text: str) -> str:
    """Pull LinkedIn/portfolio/GitHub URLs from anywhere in the resume into the contact block."""
    if not (full_text or "").strip():
        return contact
    parsed = parse_contact(contact)
    known: set[str] = set()
    if parsed.linkedin_url:
        known.add(parsed.linkedin_url.lower().rstrip("/"))
    for _, url in parsed.links:
        known.add(url.lower().rstrip("/"))

    extras: list[str] = []
    for line in full_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        url = _extract_url(stripped)
        if not url:
            continue
        key = url.lower().rstrip("/")
        if key in known:
            continue
        known.add(key)
        label = _link_label_for(stripped, url)
        if label == "LinkedIn" or "linkedin.com" in key:
            extras.append(f"LinkedIn\n{url}")
        elif label == "GitHub" or "github.com" in key:
            extras.append(f"GitHub\n{url}")
        else:
            extras.append(f"{label}\n{url}")

    if not extras:
        return contact
    base = contact.strip()
    return f"{base}\n" + "\n".join(extras) if base else "\n".join(extras)


def contact_detail_line(contact: str) -> str:
    """Plain one-line contact string: email · phone · location · links."""
    parsed = parse_contact(contact)
    parts = list(parsed.details)
    for label, url in parsed.links:
        parts.append(f"{label}: {url}")
    return " · ".join(parts)


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


_EDU_DATE_RE = re.compile(
    r"(\d{1,2}/\d{4}|\d{4})\s*[–\-—|/to]+\s*(\d{1,2}/\d{4}|\d{4}|present|current)",
    re.I,
)
_INSTITUTION_RE = re.compile(
    r"\b(university|college|institute|instituto|escuela|school|academy|polytechnic|"
    r"technological|cifp|technológica)\b",
    re.I,
)
_DEGREE_LINE_RE = re.compile(
    r"\b(bachelor|master|doctor|ph\.?\s*d|b\.?\s*s|b\.?\s*a|m\.?\s*s|m\.?\s*a|"
    r"associate|diploma|advanced technician|technician in|degree in|systems engineering|"
    r"licenciatura|grado)\b|^advanced\b",
    re.I,
)
_LOCATION_LINE_RE = re.compile(r"^[A-Za-zÀ-ÿ0-9\s.'-]+,\s*[A-Za-zÀ-ÿ0-9\s.'-]+$")


def _is_education_date_line(line: str) -> bool:
    if _EDU_DATE_RE.search(line):
        return True
    if re.search(r"\b(19|20)\d{2}\b", line) and re.search(r"[–\-—|]", line) and len(line) < 72:
        return True
    if re.search(r"\bgpa\b", line, re.I):
        return True
    return False


def _looks_like_degree_line(line: str) -> bool:
    if _is_education_date_line(line) or _BULLET_RE.match(line):
        return False
    stripped = line.strip()
    if _LOCATION_LINE_RE.match(stripped) and len(stripped) < 72:
        return False
    return bool(_DEGREE_LINE_RE.search(stripped))


def _looks_like_institution_line(line: str) -> bool:
    if _is_education_date_line(line) or _looks_like_degree_line(line) or _BULLET_RE.match(line):
        return False
    if _INSTITUTION_RE.search(line):
        return True
    if _LOCATION_LINE_RE.match(line.strip()):
        return False
    words = line.split()
    return len(words) >= 2 and len(line) < 90 and not re.search(r"\d{4}", line)


def _split_education_entries(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return []
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _looks_like_degree_line(line) and current:
            blocks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks if blocks else [lines]


def _render_education_entry(lines: list[str]) -> str:
    if not lines:
        return ""
    degree = lines[0]
    institution: str | None = None
    dates: str | None = None
    location: str | None = None
    bodies: list[str] = []
    bullets: list[str] = []

    for line in lines[1:]:
        if _BULLET_RE.match(line):
            bullets.append(_BULLET_RE.sub("", line).strip())
        elif _is_education_date_line(line):
            if dates is None:
                dates = line
            else:
                bodies.append(line)
        elif _LOCATION_LINE_RE.match(line.strip()) and location is None:
            location = line
        elif institution is None and _looks_like_institution_line(line):
            institution = line
        else:
            bodies.append(line)

    parts = [
        f"<b><font size='10' color='#0f172a'>{escape(degree)}</font></b><br/>",
    ]
    if institution:
        parts.append(f"<font color='#334155'><b>{escape(institution)}</b></font><br/>")
    meta: list[str] = []
    if dates:
        meta.append(escape(dates))
    if location:
        meta.append(escape(location))
    if meta:
        parts.append(f"<font color='#64748b' size='8'>{' · '.join(meta)}</font><br/>")
    if bodies or bullets:
        parts.append("<br/>")
    for paragraph in bodies:
        parts.append(f"<font color='#0f172a' size='9'>{escape(paragraph)}</font><br/>")
    for bullet in bullets:
        parts.append(f"<font color='#0f172a' size='9'>• {escape(bullet)}</font><br/>")
    parts.append("<br/>")
    return "".join(parts)


def format_education_markup(content: str) -> str:
    text = sanitize_for_pdf(content or "").strip()
    if not text:
        return ""
    entries = _split_education_entries(text)
    html = "".join(_render_education_entry(entry) for entry in entries)
    return _strip_trailing_breaks(html)


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
    lowered = title.lower()
    if "experience" in lowered:
        return format_experience_markup(content)
    if "education" in lowered:
        return format_education_markup(content)
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
        fontName=body_font,
        fontSize=9,
        leading=12,
        textColor=ink,
        spaceAfter=2,
    )
    contact_name_style = ParagraphStyle(
        "ContactName",
        parent=contact_style,
        fontName=heading_font,
        fontSize=15,
        leading=18,
        spaceAfter=2,
    )
    contact_detail_style = ParagraphStyle(
        "ContactDetail",
        parent=contact_style,
        fontSize=9,
        leading=12,
        textColor=muted,
        spaceAfter=4,
    )
    story: list = []

    lead = sanitize_for_pdf(contact or "").strip()
    if lead:
        parsed_contact = parse_contact(lead)
        name_html = format_contact_name_markup(parsed_contact)
        if name_html:
            story.append(Paragraph(name_html, contact_name_style))
        if parsed_contact.headline:
            story.append(Paragraph(escape(parsed_contact.headline), contact_detail_style))
        details_html = format_contact_details_markup(parsed_contact)
        if details_html:
            story.append(Paragraph(details_html, contact_detail_style))
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
