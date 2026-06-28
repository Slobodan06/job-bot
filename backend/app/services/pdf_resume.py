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
_EMAIL_IN_TEXT_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")
_EMAIL_LINE_RE = re.compile(r"^[^@\s/]+@[^@\s]+\.[^@\s]+$")
_CONTACT_SEP_RE = re.compile(r"\s*[•|·]\s*")
_BULLET_RE = re.compile(r"^[-•*–—]\s*")
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
    stripped = _strip_leading_bullet(text)
    if _is_email_part(stripped):
        return None
    cleaned = _EMAIL_IN_TEXT_RE.sub(" ", stripped)
    match = _URL_IN_TEXT_RE.search(cleaned)
    if not match:
        return None
    url = match.group(0)
    if "@" in url.split("/")[0]:
        return None
    return _normalize_url(url)


def _strip_leading_bullet(text: str) -> str:
    return _BULLET_RE.sub("", (text or "").strip()).strip()


def _is_email_part(text: str) -> bool:
    return bool(_EMAIL_LINE_RE.match(_strip_leading_bullet(text)))


def _split_contact_parts(line: str) -> list[str]:
    stripped = (line or "").strip()
    if _CONTACT_SEP_RE.search(stripped):
        return [part.strip() for part in _CONTACT_SEP_RE.split(stripped) if part.strip()]
    if re.search(r"\s-\s+", stripped) and (
        _EMAIL_IN_TEXT_RE.search(stripped)
        or _URL_IN_TEXT_RE.search(stripped)
        or re.search(r"\+?\d[\d\s().-]{7,}", stripped)
    ):
        parts = [p.strip().lstrip("-").strip() for p in re.split(r"\s+-\s+", stripped) if p.strip()]
        if len(parts) > 1:
            return parts
    if "|" in stripped:
        return [part.strip() for part in stripped.split("|") if part.strip()]
    return [stripped]


def _is_contact_detail_part(part: str) -> bool:
    cleaned = _strip_leading_bullet(part)
    if not cleaned:
        return False
    if _extract_url(cleaned):
        return True
    if _is_email_part(cleaned):
        return True
    if re.search(r"\+?\d[\d\s().-]{7,}", cleaned):
        return True
    if re.search(r",\s*[A-Za-zÀ-ÿ]", cleaned) and len(cleaned) < 72:
        return True
    return False


def _ingest_contact_part(parsed: ParsedContact, part: str) -> None:
    cleaned = _strip_leading_bullet(part)
    if not cleaned:
        return
    url = _extract_url(cleaned)
    if url:
        _register_link(parsed, _link_label_for(cleaned, url), url)
        return
    if _is_email_part(cleaned):
        parsed.details.append(cleaned)
        return
    if _is_contact_detail_part(cleaned):
        parsed.details.append(cleaned)


def _href_markup(label: str, url: str, color: str = "#0d9488") -> str:
    return (
        f'<a href="{escape(_normalize_url(url))}">'
        f'<font color="{color}">{escape(label)}</font></a>'
    )


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
    key = (url or "").lower()
    line_lower = (line or "").lower().strip().rstrip(": ")
    if "linkedin.com" in key or line_lower == "linkedin":
        return "LinkedIn"
    if "github.com" in key or line_lower == "github":
        return "GitHub"
    if "portfolio" in line_lower or "behance" in key or "dribbble" in key:
        return "Portfolio"
    if line_lower in _LINK_LABELS:
        return line.strip().rstrip(": ").title()
    if "website" in line_lower or "blog" in line_lower:
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
    if "linkedin.com" in key:
        parsed.linkedin_url = parsed.linkedin_url or url
        parsed.links.append(("LinkedIn", url))
        return
    if label.lower() == "linkedin":
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
        parts = _split_contact_parts(line)

        if len(parts) > 1:
            headline_bits: list[str] = []
            for part in parts:
                if _is_contact_detail_part(part):
                    _ingest_contact_part(parsed, part)
                else:
                    cleaned = _strip_leading_bullet(part)
                    if cleaned:
                        headline_bits.append(cleaned)
            if headline_bits:
                headline_parts.append(" · ".join(headline_bits))
            i += 1
            continue

        url = _extract_url(line)
        if url:
            _register_link(parsed, _link_label_for(line, url), url)
            i += 1
            continue

        if _is_link_label_line(line):
            labels: list[str] = []
            j = i
            while j < len(lines) and _is_link_label_line(lines[j]):
                labels.append(lines[j].strip().rstrip(": ").title())
                j += 1
            urls: list[tuple[str, str]] = []
            while j < len(lines):
                part_url = _extract_url(lines[j])
                if part_url:
                    urls.append((lines[j], part_url))
                    j += 1
                else:
                    break
            if labels and urls:
                for idx, (url_line, part_url) in enumerate(urls):
                    lbl = labels[idx] if idx < len(labels) else _link_label_for(url_line, part_url)
                    _register_link(parsed, lbl, part_url)
                i = j
                continue
            i += 1
            continue

        if _is_email_part(line):
            parsed.details.append(_strip_leading_bullet(line))
            i += 1
            continue

        if _is_contact_detail_part(line):
            _ingest_contact_part(parsed, line)
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
            f'<a href="{escape(_normalize_url(parsed.linkedin_url))}">'
            f'<font color="{color}"><b>{escape(parsed.name)}</b></font></a>'
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
    link_attr = f' color="{link_color or name_color or "#0d9488"}"' if (link_color or name_color) else ""
    if parsed.linkedin_url:
        name_html = (
            f'<a href="{escape(_normalize_url(parsed.linkedin_url))}">'
            f"<b><font size='{name_size}'{name_attr}{link_attr}>"
            f"{escape(parsed.name)}</font></b></a>"
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


def _extract_http_links_from_pdf(pdf_bytes: bytes) -> list[tuple[str, str]]:
    """Read clickable http(s) URIs embedded in a PDF (not visible in plain-text extraction)."""
    if not pdf_bytes:
        return []
    try:
        import fitz
    except ImportError:
        return []

    labeled: list[tuple[str, str]] = []
    seen: set[str] = set()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page in doc:
            for link in page.get_links():
                uri = (link.get("uri") or "").strip()
                if not uri.lower().startswith(("http://", "https://")):
                    continue
                url = _normalize_url(uri)
                key = url.lower().rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                labeled.append((_link_label_for("", url), url))
    finally:
        doc.close()
    return labeled


def merge_profile_links_into_contact(
    contact: str,
    full_text: str,
    *,
    pdf_bytes: bytes | None = None,
) -> str:
    """Pull profile URLs from PDF hyperlinks, header/footer text, and the contact block."""
    parsed = parse_contact(contact)
    known: set[str] = set()
    if parsed.linkedin_url:
        known.add(parsed.linkedin_url.lower().rstrip("/"))
    for _, url in parsed.links:
        known.add(url.lower().rstrip("/"))

    extras: list[str] = []

    if (full_text or "").strip():
        all_lines = full_text.splitlines()
        scan_lines: list[str] = list(all_lines[:25])
        if len(all_lines) > 40:
            scan_lines.extend(all_lines[-12:])
        for line in all_lines:
            lower = line.lower()
            if "linkedin.com" in lower or "github.com" in lower:
                scan_lines.append(line)

        seen_scan: set[str] = set()
        for line in scan_lines:
            stripped = line.strip()
            if not stripped or stripped in seen_scan:
                continue
            seen_scan.add(stripped)
            url = _extract_url(stripped)
            if not url:
                continue
            label = _link_label_for(stripped, url)
            key = url.lower().rstrip("/")
            if key in known:
                continue
            known.add(key)
            if label == "LinkedIn":
                if "linkedin.com" not in key:
                    continue
                extras.append(f"LinkedIn\n{url}")
            elif label == "GitHub" or "github.com" in key:
                extras.append(f"GitHub\n{url}")
            else:
                extras.append(f"{label}\n{url}")

    if pdf_bytes:
        for label, url in _extract_http_links_from_pdf(pdf_bytes):
            key = url.lower().rstrip("/")
            if key in known:
                continue
            if label == "LinkedIn" and "linkedin.com" not in key:
                continue
            known.add(key)
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

    html_parts = [_render_experience_block(lines) for lines in line_blocks]
    return _strip_trailing_breaks("".join(html_parts))


_EXP_SUMMARY_START_RE = re.compile(
    r"^(Developed|Designed|Built|Led|Managed|Created|Implemented|Worked|Collaborated|"
    r"Spearheaded|Optimized|Delivered|Architected|Engineered|Maintained|Established|"
    r"Provided|Supported|Integrated|Automated|Improved|Streamlined)\b",
    re.I,
)


def _looks_like_exp_location(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _is_education_date_line(line):
        return False
    if _LOCATION_LINE_RE.match(stripped):
        return True
    if len(stripped) > 48 or len(stripped.split()) > 5:
        return False
    if _EXP_SUMMARY_START_RE.match(stripped):
        return False
    if stripped.endswith(".") and len(stripped.split()) > 4:
        return False
    return bool(re.match(r"^[A-ZÀ-ÿ]", stripped))


def _looks_like_summary_line(line: str) -> bool:
    if len(line) > 95:
        return True
    if _EXP_SUMMARY_START_RE.match(line):
        return True
    if line.rstrip().endswith(".") and len(line.split()) > 10:
        return True
    return False


def _render_experience_block(lines: list[str]) -> str:
    if not lines:
        return ""
    title = lines[0]
    pre: list[str] = []
    bullets: list[str] = []
    for line in lines[1:]:
        if _BULLET_RE.match(line):
            bullets.append(_BULLET_RE.sub("", line).strip())
        elif bullets:
            bullets[-1] = f"{bullets[-1]} {line}"
        else:
            pre.append(line)

    meta: list[str] = []
    body: list[str] = []
    company: str | None = None
    for line in pre:
        if _is_education_date_line(line):
            meta.append(line)
        elif _looks_like_exp_location(line):
            meta.append(line)
        elif _looks_like_summary_line(line):
            body.append(line)
        elif company is None and len(line) < 72 and not line.rstrip().endswith("."):
            company = line
        else:
            body.append(line)

    parts = [
        f"<b><font size='10' color='#0f172a'>{escape(title)}</font></b><br/>",
    ]
    if company:
        parts.append(f"<font color='#334155'><b>{escape(company)}</b></font><br/>")
    if meta:
        parts.append(
            f"<font color='#64748b' size='8'>{' · '.join(escape(item) for item in meta)}</font><br/>"
        )
    if body:
        parts.append("<br/>")
        for paragraph in body:
            parts.append(f"<font color='#0f172a' size='9'>{escape(paragraph)}</font><br/>")
    if bullets:
        if not body:
            parts.append("<br/>")
        for bullet in bullets:
            parts.append(f"<font color='#0f172a' size='9'>• {escape(bullet)}</font><br/>")
    parts.append("<br/>")
    return "".join(parts)


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


def _looks_like_education_location(line: str) -> bool:
    stripped = line.strip()
    if (
        _is_education_date_line(line)
        or _looks_like_degree_line(line)
        or _looks_like_institution_line(line)
        or len(stripped) > 48
    ):
        return False
    if not _LOCATION_LINE_RE.match(stripped):
        return False
    city, _, country = stripped.partition(",")
    return len(city.split()) <= 4 and len(country.split()) <= 4


def _split_education_entries(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return []
    paired = _collect_paired_education_entries(lines)
    if paired:
        return paired
    stacked = _collect_stacked_education_entries(lines)
    if stacked:
        return stacked
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


def _split_compound_date_line(line: str) -> list[str]:
    if " · " not in line:
        return [line]
    parts = [part.strip() for part in line.split(" · ")]
    if len(parts) >= 2 and all(_is_education_date_line(part) for part in parts):
        return parts
    return [line]


def _collect_paired_education_entries(lines: list[str]) -> list[list[str]] | None:
    """Degree, institution, degree, institution, … then trailing dates and locations."""
    degrees = [line for line in lines if _looks_like_degree_line(line)]
    if len(degrees) < 2:
        return None
    institutions = [line for line in lines if _looks_like_institution_line(line)]
    dates: list[str] = []
    for line in lines:
        if _is_education_date_line(line):
            dates.extend(_split_compound_date_line(line))
    locations = [line for line in lines if _looks_like_education_location(line)]
    count = len(degrees)
    if not (len(institutions) >= count and len(dates) >= count and len(locations) >= count):
        return None
    first_date_idx = next(i for i, line in enumerate(lines) if _is_education_date_line(line))
    last_inst_idx = max(i for i, line in enumerate(lines) if _looks_like_institution_line(line))
    if last_inst_idx >= first_date_idx:
        return None
    return [
        [degrees[i], institutions[i], dates[i], locations[i]]
        for i in range(count)
    ]


def _collect_stacked_education_entries(lines: list[str]) -> list[list[str]] | None:
    degree_count = 0
    for line in lines:
        if _looks_like_degree_line(line):
            degree_count += 1
        else:
            break
    if degree_count < 2:
        return None

    degrees = lines[:degree_count]
    rest = lines[degree_count:]
    dates: list[str] = []
    for line in rest:
        if _is_education_date_line(line):
            dates.extend(_split_compound_date_line(line))
        elif dates:
            break
    if len(dates) < degree_count:
        return None

    institutions = [line for line in rest if _looks_like_institution_line(line)]
    locations = [line for line in rest if _looks_like_education_location(line)]

    entries: list[list[str]] = []
    for i, degree in enumerate(degrees):
        entry = [degree]
        if i < len(institutions):
            entry.append(institutions[i])
        if i < len(dates):
            entry.append(dates[i])
        if i < len(locations):
            entry.append(locations[i])
        entries.append(entry)
    return entries


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
        elif _looks_like_education_location(line) and location is None:
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


_OTHER_SUBHEADER_RE = re.compile(
    r"^(certifications?|certification|additional\s+strengths|licenses?|courses?)\s*:?\s*$",
    re.I,
)


def format_other_markup(content: str) -> str:
    text = sanitize_for_pdf(content or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    for line in [ln.strip() for ln in text.split("\n") if ln.strip()]:
        if _OTHER_SUBHEADER_RE.match(line):
            parts.append(
                f"<br/><b><font size='9' color='#334155'>{escape(line.upper())}</font></b><br/>"
            )
            continue
        stripped = line.lstrip("•").strip()
        dash_items = [p.strip() for p in re.split(r"\s+-\s+", stripped) if p.strip()]
        if len(dash_items) > 1 and line.strip().startswith(("-", "•", "*", "–", "—")):
            for item in dash_items:
                item = item.lstrip("-•* ").strip()
                if item and not _OTHER_SUBHEADER_RE.match(item):
                    parts.append(f"<font color='#0f172a' size='9'>• {escape(item)}</font><br/>")
            continue
        if _CONTACT_SEP_RE.search(stripped) and (
            line.strip().startswith(("•", "-", "*", "–", "—")) or "  •" in line
        ):
            for item in _CONTACT_SEP_RE.split(stripped):
                item = item.strip()
                if item:
                    parts.append(f"<font color='#0f172a' size='9'>• {escape(item)}</font><br/>")
            continue
        if _BULLET_RE.match(line):
            parts.append(
                f"<font color='#0f172a' size='9'>• {escape(_BULLET_RE.sub('', line).strip())}</font><br/>"
            )
        else:
            parts.append(f"<font color='#0f172a' size='9'>{escape(line)}</font><br/>")
    return _strip_trailing_breaks("".join(parts))


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
    if "other" in lowered or "additional" in lowered:
        return format_other_markup(content)
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
