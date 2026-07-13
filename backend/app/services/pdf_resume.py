"""Generate a clean, Unicode-safe PDF from tailored sections (ReportLab + embedded FiraGO)."""
from __future__ import annotations

import os
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
_BULLET_CHARS = r"\-•*–—\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219"
_BULLET_RE = re.compile(rf"^[{_BULLET_CHARS}]\s*")
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
    if _looks_like_role_header_line(line.strip()):
        return False
    if _extract_url(line):
        return True
    if _CONTACT_DETAIL_RE.search(line):
        return True
    if re.search(r",\s*[A-Za-z]", line) and not line.startswith("-"):
        return True
    return False


def line_is_factual_contact(line: str) -> bool:
    """True for email, phone, URL, and similar lines that must not be invented by tailoring."""
    stripped = _strip_leading_bullet(line)
    if not stripped:
        return False
    if _is_link_label_line(stripped):
        return True
    return _looks_like_contact_detail(stripped)


def merge_tailored_contact_block(tailored_contact: str, original_contact: str) -> str:
    """Keep job-targeted name/title lines from AI; preserve source email, phone, and links exactly."""
    tail_lines = [line.strip() for line in (tailored_contact or "").splitlines() if line.strip()]
    orig_lines = [line.strip() for line in (original_contact or "").splitlines() if line.strip()]
    factual = [line for line in orig_lines if line_is_factual_contact(line)]
    non_factual_tail = [line for line in tail_lines if not line_is_factual_contact(line)]
    if not non_factual_tail and orig_lines:
        non_factual_tail = [line for line in orig_lines if not line_is_factual_contact(line)]
    merged: list[str] = []
    seen: set[str] = set()
    for line in non_factual_tail + factual:
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(line)
    return "\n".join(merged)


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
        if line.strip() == name:
            i += 1
            continue
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
    if parsed.linkedin_url:
        parts.append(_href_markup("LinkedIn", parsed.linkedin_url, link_color))
    for label, url in parsed.links:
        if parsed.linkedin_url and url == parsed.linkedin_url:
            continue
        parts.append(_href_markup(label, url, link_color))
    return " · ".join(parts)


def format_contact_details_pipe_markup(
    parsed: ParsedContact,
    *,
    detail_color: str = "#64748b",
    link_color: str = "#0d9488",
) -> str:
    """Scott-style contact row: email | location | phone | LinkedIn."""
    parts: list[str] = []
    for item in parsed.details:
        parts.append(f'<font color="{detail_color}">{escape(item)}</font>')
    if parsed.linkedin_url:
        parts.append(_href_markup("LinkedIn", parsed.linkedin_url, link_color))
    for label, url in parsed.links:
        if parsed.linkedin_url and url == parsed.linkedin_url:
            continue
        parts.append(_href_markup(label, url, link_color))
    return " | ".join(parts)


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
    docx_bytes: bytes | None = None,
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

    if docx_bytes:
        from app.services.docx_resume import extract_http_links_from_docx

        for label, url in extract_http_links_from_docx(docx_bytes):
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
    line_blocks = _split_experience_lines(text)
    html_parts = [_render_experience_block(lines) for lines in line_blocks]
    return _strip_trailing_breaks("".join(html_parts))


_EXP_SUMMARY_START_RE = re.compile(
    r"^(Developed|Designed|Built|Led|Managed|Created|Implemented|Worked|Collaborated|"
    r"Spearheaded|Optimized|Delivered|Architected|Engineered|Maintained|Established|"
    r"Provided|Supported|Integrated|Automated|Improved|Streamlined|Conducted|"
    r"Enhanced|Applied|Utilized|Proficient)\b",
    re.I,
)
_EXP_ROLE_RE = re.compile(
    r"\b(developer|engineer|manager|director|designer|founder|co-founder|cto|lead|"
    r"architect|consultant|specialist|analyst|coordinator|head|principal)\b",
    re.I,
)


def _looks_like_exp_location(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _is_education_date_line(line) or _BULLET_RE.match(stripped):
        return False
    if _EXP_ROLE_RE.search(stripped):
        return False
    if len(stripped) > 48 or stripped.rstrip().endswith("."):
        return False
    if _EXP_SUMMARY_START_RE.match(stripped):
        return False
    if _LOCATION_LINE_RE.match(stripped):
        city, _, country = stripped.partition(",")
        return len(city.split()) <= 4 and len(country.split()) <= 4
    words = stripped.split()
    return len(words) <= 4 and bool(re.match(r"^[A-ZÀ-ÿ]", stripped))


def _looks_like_summary_line(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) > 95:
        return True
    if _EXP_SUMMARY_START_RE.match(stripped):
        return True
    if stripped.rstrip().endswith(".") and len(stripped.split()) > 8:
        return True
    return False


def _looks_like_job_title_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _BULLET_RE.match(stripped):
        return False
    if _looks_like_role_header_line(stripped):
        return True
    if _is_education_date_line(stripped):
        return False
    if _looks_like_summary_line(stripped):
        return False
    if _EXP_ROLE_RE.search(stripped) and len(stripped) < 120 and not stripped.rstrip().endswith("."):
        # Single-token lines (e.g. company names) are not job titles.
        if len(stripped.split()) == 1:
            return False
        return True
    return False


def _peel_meta_from_line(line: str) -> tuple[str, list[str]]:
    meta: list[str] = []
    rest = line.strip()
    date_match = _EDU_DATE_RE.search(rest)
    if date_match:
        meta.append(date_match.group(0).strip())
        rest = f"{rest[:date_match.start()]} {rest[date_match.end():]}".strip(" ·-|,\t")
    if " · " in rest:
        bits = [bit.strip() for bit in rest.split(" · ") if bit.strip()]
        while bits and _looks_like_exp_location(bits[-1]):
            meta.append(bits.pop())
        rest = " · ".join(bits).strip()
    elif _looks_like_exp_location(rest):
        meta.append(rest)
        rest = ""
    return rest.strip(), meta


def _render_experience_block(lines: list[str]) -> str:
    if not lines:
        return ""
    meta: list[str] = []
    if _BULLET_RE.match(lines[0]):
        title = "Professional Experience"
        embedded_meta, skip_lines = _meta_from_bullet_first_block(lines)
        meta.extend(embedded_meta)
        body_lines = [line for i, line in enumerate(lines) if i not in skip_lines]
    else:
        title = lines[0]
        body_lines = lines[1:]
        if body_lines and _looks_like_company_line(body_lines[0]):
            meta.append(body_lines[0].strip())
            body_lines = body_lines[1:]
    body: list[str] = []
    bullets: list[str] = []
    current_bullet: str | None = None

    def flush_bullet() -> None:
        nonlocal current_bullet
        if current_bullet:
            bullets.append(current_bullet.strip())
            current_bullet = None

    for line in body_lines:
        if _is_education_date_line(line):
            flush_bullet()
            meta.append(line.strip())
            continue
        if _looks_like_exp_location(line):
            if title == line.strip() or (meta and line.strip() in title):
                continue
            flush_bullet()
            meta.append(line.strip())
            continue
        if _BULLET_RE.match(line):
            flush_bullet()
            current_bullet = _BULLET_RE.sub("", line).strip()
            continue
        if current_bullet is not None:
            current_bullet = f"{current_bullet} {line}"
            continue

        peeled, inline_meta = _peel_meta_from_line(line)
        meta.extend(inline_meta)
        if peeled and _looks_like_summary_line(peeled):
            body.append(peeled)
        elif peeled:
            body.append(peeled)

    flush_bullet()

    parts = [
        f"<b><font size='10' color='#0f172a'>{escape(title)}</font></b><br/>",
    ]
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


def _block_has_date(block: list[str]) -> bool:
    return any(_is_education_date_line(line) for line in block)


def _looks_like_company_line(line: str) -> bool:
    stripped = line.strip()
    if (
        not stripped
        or _BULLET_RE.match(stripped)
        or _is_education_date_line(stripped)
        or _looks_like_job_title_line(stripped)
        or stripped.endswith(".")
        or len(stripped) > 90
    ):
        return False
    return True


def _infer_title_from_bullet_block(block: list[str]) -> str | None:
    """Two-column PDFs may omit the role title; do not treat company/location as the title."""
    return None


def _meta_from_bullet_first_block(block: list[str]) -> tuple[list[str], set[int]]:
    """Collect date and company/location lines embedded inside a bullet-first block."""
    meta: list[str] = []
    skip: set[int] = set()
    for i, line in enumerate(block):
        if not _is_education_date_line(line):
            continue
        meta.append(line.strip())
        skip.add(i)
        j = i + 1
        company_parts: list[str] = []
        while j < len(block):
            nxt = block[j].strip()
            if _BULLET_RE.match(nxt) or _is_education_date_line(nxt) or _looks_like_job_title_line(nxt):
                break
            if len(nxt) < 50 and not nxt.endswith("."):
                company_parts.append(nxt.rstrip(","))
                skip.add(j)
                j += 1
            else:
                break
        if company_parts:
            meta.append(" ".join(company_parts))
        break
    return meta, skip


def _pop_trailing_date_meta(block: list[str]) -> list[str]:
    meta: list[str] = []
    while block and (_is_education_date_line(block[-1]) or _looks_like_exp_location(block[-1])):
        meta.insert(0, block.pop())
    return meta


def _insert_date_meta_after_company(block: list[str], meta: list[str]) -> None:
    insert_at = 1
    if len(block) > 1 and _looks_like_company_line(block[1]):
        insert_at = 2
    for offset, line in enumerate(meta):
        block.insert(insert_at + offset, line)


def _should_rebalance_experience_blocks(blocks: list[list[str]]) -> bool:
    """Table-export resumes include bullets and trailing dates per role — skip PDF rebalance."""
    for block in blocks:
        if any(_BULLET_RE.match(line.strip()) for line in block):
            return False
    return True


def _rebalance_experience_date_groups(blocks: list[list[str]]) -> list[list[str]]:
    """Reassign trailing date meta when a two-column PDF leaves one role without dates."""
    blocks = [list(block) for block in blocks]
    titled = [i for i, block in enumerate(blocks) if block and _looks_like_job_title_line(block[0])]
    if len(titled) < 2:
        return blocks

    groups = [_pop_trailing_date_meta(blocks[idx]) for idx in titled]
    pooled = [group for group in groups if group]
    if not pooled:
        return blocks

    if len(pooled) == len(titled):
        for idx, meta in zip(titled, groups):
            if meta:
                _insert_date_meta_after_company(blocks[idx], meta)
        return blocks

    if len(pooled) == len(titled) - 1:
        skip_index = 1 if len(titled) == 4 else (len(titled) - 1) // 2
        pool_iter = iter(pooled)
        for slot, idx in enumerate(titled):
            if slot == skip_index:
                continue
            meta = next(pool_iter, None)
            if meta:
                _insert_date_meta_after_company(blocks[idx], meta)
        return blocks

    for idx, meta in zip(titled, groups):
        if meta:
            _insert_date_meta_after_company(blocks[idx], meta)
    return blocks


def _split_experience_lines(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    blocks: list[list[str]] = []
    current: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if _looks_like_job_title_line(line) or (
            current
            and any(_BULLET_RE.match(entry) for entry in current)
            and is_experience_role_header_line(line)
        ):
            if current:
                blocks.append(current)
            current = [line]
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                if _looks_like_company_line(nxt):
                    current.append(nxt)
                    i += 1
        elif _is_education_date_line(line):
            if current and any(_BULLET_RE.match(entry) for entry in current):
                current.append(line)
            elif _block_has_date(current):
                blocks.append(current)
                current = [line]
            else:
                current.append(line)
        else:
            current.append(line)
        i += 1
    if current:
        blocks.append(current)
    if _should_rebalance_experience_blocks(blocks):
        return _rebalance_experience_date_groups(blocks)
    return blocks


def is_experience_role_header_line(line: str) -> bool:
    """True for 'Title | Company | Location | MM/YYYY – MM/YYYY' experience headers."""
    return _looks_like_role_header_line((line or "").strip())


def split_experience_line_blocks(text: str) -> list[list[str]]:
    """Public API: group experience plain-text lines into per-role blocks."""
    return _split_experience_lines(text)


_BULLET_LINE_RE = re.compile(rf"^[{_BULLET_CHARS}]\s+")


def _min_bullets_per_role_env() -> int:
    raw = os.getenv("OPENAI_MIN_BULLETS_PER_ROLE", "2").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 2
    return max(1, min(n, 8))


def ats_bullets_for_generation(
    ats_targets: list[int],
    *,
    min_per_role: int | None = None,
    max_per_role: int = 22,
) -> list[int]:
    """
    Bullet targets for LLM generation and API text merge.
    NOT capped by how many bullets the source resume happened to have — only by ATS targets and min floor.
    """
    floor = min_per_role if min_per_role is not None else _min_bullets_per_role_env()
    if not ats_targets:
        return [floor]
    return [max(floor, min(ats, max_per_role)) for ats in ats_targets]


def effective_bullets_per_role(
    ats_targets: list[int],
    template_slots: list[int],
    *,
    min_per_role: int = 3,
) -> list[int]:
    """
    ATS bullet targets capped to each role's Word template slot count.
    Every role gets at least min(3, slots) bullets when slots allow — never 1 bullet in a 3-slot role.
    """
    if not template_slots:
        return list(ats_targets)
    out: list[int] = []
    for i, slots in enumerate(template_slots):
        if slots <= 0:
            out.append(0)
            continue
        ats = ats_targets[i] if i < len(ats_targets) else min_per_role
        floor = min(min_per_role, slots)
        out.append(max(floor, min(ats, slots)))
    return out


def fill_experience_bullets_to_minimums(
    source: str,
    tailored_bullets: list[str],
    minimums_per_role: list[int],
) -> list[str]:
    """
    When the LLM returns too few bullets for a role, pad from source accomplishments for that employer.
    Keeps chronological order; does not exceed per-role minimums (template slot caps).
    """
    source_blocks = split_experience_line_blocks(source or "")
    if not minimums_per_role:
        return list(tailored_bullets)
    partitioned = partition_experience_bullets_by_role(tailored_bullets, minimums_per_role)
    filled: list[str] = []
    for block_i, minimum in enumerate(minimums_per_role):
        role_bullets = list(partitioned[block_i]) if block_i < len(partitioned) else []
        src_block = source_blocks[block_i] if block_i < len(source_blocks) else []
        src_bullets = [
            line.strip()
            for line in src_block
            if line.strip() and _BULLET_LINE_RE.match(line.strip())
        ]
        seen = {b.lower() for b in role_bullets}
        for src_bullet in src_bullets:
            if len(role_bullets) >= minimum:
                break
            key = src_bullet.lower()
            if key not in seen:
                role_bullets.append(src_bullet)
                seen.add(key)
        filled.extend(role_bullets[:minimum])
    return filled


def default_ats_bullets_per_role(role_count: int) -> list[int]:
    """
    Minimum ATS bullets per role (oldest first). Independent of source resume bullet counts.
    Recent roles get substantially more bullets for keyword density.
    """
    if role_count <= 0:
        return []
    if role_count == 1:
        return [22]

    newest = min(22, 16 + role_count * 2)
    oldest = max(5, round(newest * 0.28))
    if role_count == 2:
        return [oldest, newest]

    counts: list[int] = []
    for i in range(role_count):
        t = i / (role_count - 1)
        value = oldest + (newest - oldest) * (t**1.35)
        counts.append(max(6, round(value)))

    for i in range(1, len(counts)):
        if counts[i] <= counts[i - 1]:
            counts[i] = counts[i - 1] + 4
    return counts


def partition_experience_bullets_by_role(
    bullets: list[str],
    minimums_per_role: list[int],
) -> list[list[str]]:
    """
    Split a flat bullet list across roles in order.
    Reserves bullets for later roles so no role is left empty when bullets are available.
    """
    if not minimums_per_role:
        return [bullets] if bullets else []
    role_count = len(minimums_per_role)
    if not bullets:
        return [[] for _ in minimums_per_role]

    out: list[list[str]] = []
    pos = 0
    total = len(bullets)
    for i, minimum in enumerate(minimums_per_role):
        remaining_roles = role_count - i
        remaining_bullets = total - pos
        if i < role_count - 1:
            max_take = max(0, remaining_bullets - (remaining_roles - 1))
            take = min(max(minimum, 1), max_take) if remaining_bullets > 0 else 0
            chunk = bullets[pos : pos + take]
            pos += len(chunk)
        else:
            chunk = bullets[pos:]
        out.append(chunk)
    return out


def _partition_bullets_for_role_blocks(bullets: list[str], counts: list[int]) -> list[list[str]]:
    return partition_experience_bullets_by_role(bullets, counts)


_EXPERIENCE_DATE_RANGE_RE = re.compile(
    r"\b\d{1,2}/\s*\d{4}\s*[–\-—]\s*(?:\d{1,2}/\s*\d{4}|present|current)\b",
    re.I,
)
_ROLE_HEADER_DATE_RE = _EXPERIENCE_DATE_RANGE_RE


def has_experience_date_range(line: str) -> bool:
    """True when a line contains MM/YYYY – MM/YYYY (or Present) employment dates."""
    return bool(_EXPERIENCE_DATE_RANGE_RE.search((line or "").strip()))
_ROLE_HEADER_TITLE_RE = re.compile(
    r"\b(developer|engineer|manager|lead|specialist|architect|consultant|analyst|"
    r"director|coordinator|head|principal|designer|operations?|automation|fullstack|"
    r"full[\s-]?stack|programmer|administrator)\b",
    re.I,
)
_SENIORITY_PREFIX_RE = re.compile(
    r"^(senior|lead|principal|staff|junior|associate|mid[\s-]?level)\s+",
    re.I,
)
_JD_ROLE_LINE_RE = re.compile(
    r"^([A-Z][A-Za-z0-9/&\s-]{3,70}(?:Engineer|Developer|Manager|Specialist|Architect|"
    r"Analyst|Lead|Coordinator|Administrator|Officer))\s*(?:[-–—|]|$)",
    re.M,
)
_JD_ABOUT_ROLE_RE = re.compile(
    r"(?:about the role|the role|position title|job title|role title)[:\s-]*\n+\s*([^\n]{5,90})",
    re.I,
)


def _looks_like_role_header_line(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped or _BULLET_LINE_RE.match(stripped):
        return False
    if re.search(r"@|\+\d{1,3}|\(\d{3}\)\s*\d", stripped):
        return False
    if has_experience_date_range(stripped):
        return True
    if "|" in stripped and len(stripped) < 140 and _ROLE_HEADER_TITLE_RE.search(stripped):
        return True
    return bool(_ROLE_HEADER_TITLE_RE.search(stripped) and len(stripped) < 100)


def primary_role_header_from_block(block: list[str]) -> str | None:
    """First job header line in a role block (title/company/location/dates)."""
    for line in block:
        stripped = line.strip()
        if not stripped or _BULLET_LINE_RE.match(stripped):
            continue
        if _looks_like_role_header_line(stripped):
            return stripped
    for line in block:
        stripped = line.strip()
        if stripped and not _BULLET_LINE_RE.match(stripped):
            return stripped
    return None


def replace_role_title_in_header(header_line: str, new_title: str) -> str:
    """Swap only the job-title segment; keep company, location, and dates from source."""
    title = (new_title or "").strip()
    if not title:
        return header_line
    stripped = (header_line or "").strip()
    if "|" in stripped:
        _, rest = stripped.split("|", 1)
        return f"{title} | {rest.lstrip()}"
    if stripped.endswith("|"):
        return f"{title} |"
    if "\t" in stripped:
        _, rest = stripped.split("\t", 1)
        return f"{title}\t{rest.lstrip()}"
    date_match = _ROLE_HEADER_DATE_RE.search(stripped)
    if date_match:
        rest = stripped[date_match.start() :].lstrip()
        sep = "\t" if "\t" in stripped else " "
        return f"{title}{sep}{rest}"
    return title


def parse_experience_role_titles(experience: str, *, expected_count: int | None = None) -> list[str]:
    """Extract the title portion from each role header line in order."""
    titles: list[str] = []
    for block in split_experience_line_blocks(experience or ""):
        header = primary_role_header_from_block(block)
        if not header:
            continue
        if "|" in header:
            titles.append(header.split("|", 1)[0].strip())
        else:
            titles.append(header.rstrip("|").strip())
    if expected_count and len(titles) != expected_count:
        return titles[:expected_count] if len(titles) > expected_count else titles
    return titles


def extract_seniority_prefix(title: str) -> str:
    match = _SENIORITY_PREFIX_RE.match((title or "").strip())
    return match.group(1).strip() if match else ""


def blend_role_title_with_jd(source_title: str, jd_role: str) -> str:
    """Keep seniority from source; swap core role wording to match the job description."""
    source = (source_title or "").strip()
    target = (jd_role or "").strip()
    if not target:
        return source
    if not source:
        return target
    prefix = extract_seniority_prefix(source)
    if prefix and not re.match(rf"^{re.escape(prefix)}\b", target, re.I):
        return f"{prefix} {target}"
    return target


def sanitize_target_job_role(role: str) -> str:
    """Normalize the user-provided application job title."""
    s = re.sub(r"\s+", " ", (role or "").strip())
    if not s:
        return ""
    s = re.sub(
        r"^(?:as\s+(?:an?\s+)?|the\s+|role\s*:|position\s*:|job\s*title\s*:)\s*",
        "",
        s,
        flags=re.I,
    ).strip()
    return s.strip(" .,:;-")


def build_experience_role_titles_from_target(
    target_job_role: str,
    source_experience: str,
    *,
    expected_count: int | None = None,
) -> list[str]:
    """Apply the user-provided target role to every work-experience entry (title line only)."""
    target = sanitize_target_job_role(target_job_role)
    if not target:
        return []
    count = expected_count
    if count is None:
        count = len(parse_experience_role_titles(source_experience)) or 1
    return [target] * max(count, 1)


def extract_jd_target_role_title(job_description: str) -> str | None:
    """Best-effort extraction of the target role title from a job description."""
    jd = (job_description or "").strip()
    if not jd:
        return None

    about = _JD_ABOUT_ROLE_RE.search(jd)
    if about:
        candidate = about.group(1).strip().split("|", 1)[0].strip()
        if 4 < len(candidate) < 90:
            return candidate

    for match in _JD_ROLE_LINE_RE.finditer(jd):
        candidate = match.group(1).strip()
        if len(candidate) > 4 and not re.search(r"\b(you|we|our|the candidate)\b", candidate, re.I):
            return candidate

    also_known = re.search(
        r"also known as:\s*([^\n]+)",
        jd,
        re.I,
    )
    if also_known:
        first = also_known.group(1).split("|", 1)[0].strip()
        if 4 < len(first) < 90:
            return first

    return None


def resolve_tailored_role_titles(
    source_experience: str,
    llm_titles: list[str],
    job_description: str,
    *,
    expected_count: int | None = None,
) -> list[str]:
    """
    One JD-aligned title per work-experience role (same order as source).
    Uses LLM titles when complete; otherwise blends each source title with the JD role.
    """
    source_titles = parse_experience_role_titles(source_experience, expected_count=expected_count)
    if not source_titles:
        return llm_titles

    if expected_count and len(source_titles) != expected_count:
        source_titles = source_titles[:expected_count]

    jd_role = extract_jd_target_role_title(job_description)
    if llm_titles and len(llm_titles) == len(source_titles):
        return llm_titles

    if llm_titles and len(llm_titles) < len(source_titles):
        out = list(llm_titles)
        for i in range(len(llm_titles), len(source_titles)):
            out.append(
                blend_role_title_with_jd(source_titles[i], jd_role or llm_titles[-1])
                if jd_role or llm_titles
                else source_titles[i]
            )
        return out

    if jd_role:
        return [blend_role_title_with_jd(src, jd_role) for src in source_titles]

    return llm_titles if llm_titles else source_titles


def merge_experience_role_titles(source: str, tailored_titles: list[str]) -> str:
    """Apply JD-tailored job titles while preserving company, location, and dates."""
    source = (source or "").strip()
    if not source or not tailored_titles:
        return source
    blocks = split_experience_line_blocks(source)
    if not blocks:
        return source

    out: list[str] = []
    for block_i, block in enumerate(blocks):
        new_block = list(block)
        if block_i < len(tailored_titles) and tailored_titles[block_i].strip():
            new_title = tailored_titles[block_i].strip()
            for line_i, line in enumerate(new_block):
                if _BULLET_LINE_RE.match(line.strip()):
                    break
                if _looks_like_role_header_line(line):
                    new_block[line_i] = replace_role_title_in_header(line, new_title)
                    break
                if line_i == 0 and not _BULLET_LINE_RE.match(line):
                    new_block[line_i] = new_title if "|" not in line else replace_role_title_in_header(line, new_title)
                    break
        out.extend(new_block)
        if block_i < len(blocks) - 1:
            out.append("")
    return "\n".join(out).strip()


def merge_experience_headers_with_bullets(
    source: str,
    tailored: str,
    *,
    tailored_role_titles: list[str] | None = None,
    bullets_per_role: list[int] | None = None,
) -> str:
    """
    Keep company/location/date lines from source; replace job titles and bullet lines
    with tailored content in order.
    """
    source = (source or "").strip()
    tailored = (tailored or "").strip()
    if tailored_role_titles:
        source = merge_experience_role_titles(source, tailored_role_titles)
    if not source:
        return tailored
    if not tailored:
        return source

    source_blocks = split_experience_line_blocks(source)
    tailored_bullets = [
        line.strip()
        for line in tailored.splitlines()
        if line.strip() and _BULLET_LINE_RE.match(line.strip())
    ]
    if bullets_per_role and len(bullets_per_role) == len(source_blocks) and tailored_bullets:
        tailored_bullets = fill_experience_bullets_to_minimums(
            source,
            tailored_bullets,
            bullets_per_role,
        )
    if not tailored_bullets:
        if not source_blocks:
            return tailored
        out: list[str] = []
        for block_i, block in enumerate(source_blocks):
            headers = [line for line in block if not _BULLET_LINE_RE.match(line.strip())]
            out.extend(headers)
            if block_i < len(source_blocks) - 1:
                out.append("")
        return "\n".join(out).strip()

    role_count = len(source_blocks)
    if bullets_per_role and len(bullets_per_role) == role_count:
        bullet_counts = bullets_per_role
    else:
        bullet_counts = default_ats_bullets_per_role(role_count)
    bullets_by_block = partition_experience_bullets_by_role(tailored_bullets, bullet_counts)

    out: list[str] = []
    for block_i, block in enumerate(source_blocks):
        headers = [line for line in block if not _BULLET_LINE_RE.match(line.strip())]
        new_bullets = bullets_by_block[block_i] if block_i < len(bullets_by_block) else []
        out.extend(headers)
        out.extend(new_bullets)
        if block_i < len(source_blocks) - 1:
            out.append("")
    return "\n".join(out).strip()


def merge_skills_preserving_labels(source: str, tailored: str) -> str:
    """Prefer tailored skill lines (labels + lists); fall back to source labels when tailored omits a label."""
    source_lines = [line.strip() for line in (source or "").splitlines() if line.strip()]
    tailored_lines = [line.strip() for line in (tailored or "").splitlines() if line.strip()]
    if not source_lines:
        return "\n".join(tailored_lines)
    if not tailored_lines:
        return "\n".join(source_lines)

    merged: list[str] = []
    for i, src in enumerate(source_lines):
        if i >= len(tailored_lines):
            merged.append(src)
            continue
        tailored_line = tailored_lines[i]
        tailored_match = re.match(r"^([^:]+:)\s*(.*)$", tailored_line)
        if tailored_match:
            merged.append(tailored_line.strip())
            continue
        label_match = re.match(r"^([^:]+:)\s*(.*)$", src)
        if not label_match:
            merged.append(tailored_line)
            continue
        label = label_match.group(1)
        merged.append(f"{label} {tailored_line}".strip())
    if len(tailored_lines) > len(source_lines):
        merged.extend(tailored_lines[len(source_lines) :])
    return "\n".join(merged)


def merge_skills_for_ats(source: str, tailored: str, *, replace_entirely: bool = False) -> str:
    """Replace the entire skills section for ATS (AI roles) or merge line-by-line."""
    tailored_lines = [line.strip() for line in (tailored or "").splitlines() if line.strip()]
    if replace_entirely and tailored_lines:
        return "\n".join(tailored_lines)
    return merge_skills_preserving_labels(source, tailored)


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


def build_scott_ats_professional_pdf(
    *,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    """Single-column ATS layout: pipe contact row, pipe job headers, Technical Skills section."""
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
        "ScottSecHeading",
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
        "ScottSecBody",
        parent=base["Normal"],
        fontName=body_font,
        fontSize=9.5,
        leading=13,
        alignment=TA_LEFT,
        textColor=ink,
        wordWrap="CJK",
    )
    contact_name_style = ParagraphStyle(
        "ScottContactName",
        parent=body,
        fontName=heading_font,
        fontSize=15,
        leading=18,
        spaceAfter=2,
    )
    contact_detail_style = ParagraphStyle(
        "ScottContactDetail",
        parent=body,
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
        details_html = format_contact_details_pipe_markup(parsed_contact)
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
    add_section("Technical Skills", skills)
    add_section("Professional Experience", professional_experience)
    add_section("Education", education)
    add_section("Additional", other)

    if len(story) == 0:
        story.append(Paragraph(_para_markup("(No content)"), body))

    doc.build(story)
    return buf.getvalue()
