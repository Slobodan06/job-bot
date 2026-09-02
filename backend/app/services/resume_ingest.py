"""Convert an uploaded resume file into the canonical :class:`ResumeModel`.

Pipeline:
    1. detect format (extension + magic bytes)
    2. extract raw plain text (``extract_text_from_bytes``)
    3. build a deterministic first-pass model from the existing heuristic parsers
    4. optional AI normalization pass, validated against the raw text
    5. deterministic candidate-location recovery
"""
from __future__ import annotations

import logging
import re

from app.services.extract_text import extract_text_from_bytes
from app.services.pdf_resume import (
    has_experience_date_range,
    is_experience_role_header_line,
    parse_contact_identity,
)
from app.services.rendercv_resume import _education_entries
from app.services.resume_model import (
    ResumeContact,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeMeta,
    ResumeModel,
    skills_dict_from_text,
)
from app.services.resume_sections import analyze_resume_file
from app.services.sectionize import is_pure_section_header

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK"

_CERT_HEADING_RE = re.compile(r"^(certification|certificate|license|licence)s?\b", re.I)
_LANG_HEADING_RE = re.compile(r"^(language)s?\b", re.I)
_EXTRA_HEADING_RE = re.compile(
    r"^(award|honou?r|publication|project|volunteer|interest|hobby|activity|reference|"
    r"course|training|professional development|affiliation|membership|patent|"
    r"speaking|talk|additional( information| info| details)?)s?\b",
    re.I,
)
_LOCATION_RE = re.compile(
    r"\b([A-Z][A-Za-zÀ-ÿ.'-]+(?:\s+[A-Z][A-Za-zÀ-ÿ.'-]+)*"
    r"(?:,\s*[A-Z][A-Za-zÀ-ÿ.'-]+(?:\s+[A-Za-zÀ-ÿ.'-]+)*){1,3})\b"
)
_LOCATION_STOPWORDS = re.compile(
    r"\b(react|python|node|java|aws|azure|api|apis|llm|rag|ai|ml|sql|docker|kubernetes|"
    r"engineer|developer|manager|architect|university|college|institute|inc|llc|ltd|corp)\b",
    re.I,
)
_COUNTRY_HINT_RE = re.compile(
    r"(united states|usa|u\.s\.a?\.?|canada|united kingdom|uk|australia|germany|india|"
    r"\b[A-Z]{2}\b)$",
    re.I,
)
_ROLE_WORD_RE = re.compile(
    r"\b(engineer|developer|manager|architect|consultant|analyst|designer|specialist|"
    r"lead|principal|scientist|programmer|administrator|director|coordinator|"
    r"intern|founder|owner|head|officer|full[- ]?stack|frontend|backend|devops|sre)\b",
    re.I,
)


def _looks_like_bare_location(headline: str, location: str) -> bool:
    """True when a parsed 'headline' is really a place name, not a professional title.

    Resume headlines carry a role ("Senior Software Engineer", "Full-Stack
    Developer | Cloud Architect"). A bare city, a "City, Region" pair, or a
    line that just repeats the candidate's location is not a title.
    """
    text = re.sub(r"\s+", " ", (headline or "").strip(" -·|,")).strip()
    if not text or _ROLE_WORD_RE.search(text):
        return False
    loc = (location or "").casefold()
    parts = {p.strip().casefold() for p in re.split(r"\s*[-·|]\s*|\s{2,}", text) if p.strip()}
    if loc and parts and all(p == loc or p in loc for p in parts):
        return True
    # A single repeated / lone token that is one Capitalized word ("Dublin").
    if len(parts) == 1:
        token = next(iter(parts))
        if re.fullmatch(r"[a-zà-ÿ][a-zà-ÿ.'-]{1,20}", token):
            return True
    # "City, Region" / "City, Region, Country" with no role word.
    if "," in text and re.fullmatch(
        r"[A-Z][\wÀ-ÿ.'-]*(?:\s+[A-Z][\wÀ-ÿ.'-]*)*(?:,\s*[\wÀ-ÿ.'-]+(?:\s+[\wÀ-ÿ.'-]+)*){1,3}",
        text,
    ):
        return True
    return False


def detect_source_format(data: bytes, filename: str) -> str:
    name = (filename or "").lower()
    if data[:4] == _PDF_MAGIC or name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".doc") and data[:2] != _ZIP_MAGIC:
        return "doc"
    if data[:2] == _ZIP_MAGIC or name.endswith((".docx", ".doc")):
        return "docx"
    raise ValueError("Unsupported file type. Upload a Word (.docx) or PDF (.pdf) resume.")


def guess_candidate_location(raw_text: str) -> str:
    """Recover the candidate's own city/region from the resume header block."""
    lines = [line.strip() for line in (raw_text or "").splitlines() if line.strip()]
    header = lines[:18]
    name = lines[0] if lines else ""

    # 1) A multi-part "City, Region[, Country]" anywhere in the header.
    for line in header:
        if is_experience_role_header_line(line) or has_experience_date_range(line):
            continue
        for segment in re.split(r"[|•·]|\s{2,}", line):
            segment = segment.strip(" ,-")
            if not segment or "@" in segment or re.search(r"https?://|\d{5,}", segment):
                continue
            match = _LOCATION_RE.search(segment)
            if not match:
                continue
            candidate = match.group(1).strip(" ,-")
            if _LOCATION_STOPWORDS.search(candidate):
                continue
            parts = [p.strip() for p in candidate.split(",") if p.strip()]
            if 2 <= len(parts) and len(candidate) <= 90:
                return candidate

    # 2) A lone one/two-word Title-Case token in the header ("Dublin") that also
    #    shows up elsewhere as an employer location or in the contact line.
    body = "\n".join(lines[len(header):]) if len(lines) > len(header) else ""
    for line in header[1:7]:
        token = line.strip(" ,-·|")
        if (
            not token
            or token == name
            or "@" in token
            or re.search(r"\d", token)
            or _LOCATION_STOPWORDS.search(token)
        ):
            continue
        if re.fullmatch(r"[A-Z][A-Za-zÀ-ÿ.'-]+(?:\s+[A-Z][A-Za-zÀ-ÿ.'-]+)?", token):
            elsewhere = f"| {token} |" in "\n".join(header) or f"| {token}\n" in "\n".join(header) or token in body
            contact_line = any(("@" in l or re.search(r"\d{3}", l)) and token in l for l in header)
            if elsewhere or contact_line:
                return token
    return ""


def _contact_and_identity(contact_block: str, raw_text: str) -> tuple[str, str, str, ResumeContact]:
    identity = parse_contact_identity(contact_block or "")
    website = identity.portfolio_url or next(
        (url for _label, url in identity.other_links if url), ""
    )
    contact = ResumeContact(
        email=identity.email,
        phone=identity.phone,
        linkedin=identity.linkedin_url,
        github=identity.github_url,
        website=website,
    )
    # The header-anchored regex keeps multi-part locations intact
    # ("Duncan, South Carolina, United States") that parse_contact_identity
    # sometimes truncates to "South Carolina, United States".
    guessed = guess_candidate_location(raw_text)
    identity_loc = (identity.location or "").strip()
    # parse_contact_identity can misfile a second phone-like line as the location.
    if identity_loc and (
        "@" in identity_loc
        or re.fullmatch(r"\+?[\d\s().\-]{7,}", identity_loc)
        or (len(re.sub(r"\D", "", identity_loc)) >= 7 and not re.search(r"[A-Za-z]{3}", identity_loc))
    ):
        identity_loc = ""
    if guessed and (not identity_loc or identity_loc in guessed):
        location = guessed
    else:
        location = identity_loc or guessed

    title = (identity.headline or "").strip()
    if _looks_like_bare_location(title, location):
        title = ""
    return identity.name, title, location, contact


def _skills_from_section(skills_text: str) -> dict[str, list[str]]:
    """Heuristic skill parsing that stops when the blob bleeds into other sections."""
    kept: list[str] = []
    for raw_line in (skills_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if has_experience_date_range(line) or is_experience_role_header_line(line):
            break
        if len(line.split()) > 14 and ":" not in line.split()[0]:
            break
        kept.append(line)
    return skills_dict_from_text("\n".join(kept))


def _experience_from_roles(roles) -> list[ResumeExperienceEntry]:
    out: list[ResumeExperienceEntry] = []
    for role in roles:
        out.append(
            ResumeExperienceEntry(
                title=(role.title or "").strip(),
                company=(role.company or "").strip(),
                dates=(role.period or "").strip(),
                location=(role.location or "").strip(),
                responsibilities=[b.strip() for b in role.bullets if b and b.strip()],
            )
        )
    return out


def _education_from_text(education_text: str) -> list[ResumeEducationEntry]:
    entries: list[ResumeEducationEntry] = []
    for entry in _education_entries(education_text or ""):
        entries.append(
            ResumeEducationEntry(
                degree=str(entry.get("degree") or "").strip(),
                field=str(entry.get("area") or "").strip(),
                school=str(entry.get("institution") or "").strip(),
                duration=str(entry.get("date") or "").strip(),
            )
        )
    return entries


def _split_other_section(other_text: str) -> tuple[list[str], list[str], list[str]]:
    """Partition the 'other' blob into certifications / languages / additional_info."""
    certs: list[str] = []
    langs: list[str] = []
    additional: list[str] = []
    bucket = additional
    for raw_line in (other_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        looks_heading = (
            _CERT_HEADING_RE.match(line)
            or _LANG_HEADING_RE.match(line)
            or _EXTRA_HEADING_RE.match(line)
            or (is_pure_section_header(line) and len(line.split()) <= 4)
            or (line.isupper() and 2 <= len(line) <= 40)
        )
        if looks_heading:
            if _CERT_HEADING_RE.match(line):
                bucket = certs
            elif _LANG_HEADING_RE.match(line):
                bucket = langs
            else:
                bucket = additional
            continue
        bucket.append(re.sub(r"^[\-*•●○▪◦·]+\s*", "", line).strip())
    return certs, langs, additional


def build_heuristic_model(data: bytes, *, filename: str, source_format: str, raw_text: str) -> ResumeModel:
    analysis = analyze_resume_file(data, filename=filename)
    name, title, location, contact = _contact_and_identity(analysis.contact, raw_text)
    certs, langs, additional = _split_other_section(analysis.other or "")
    return ResumeModel(
        name=name,
        title=title,
        location=location,
        contact=contact,
        professional_summary=(analysis.professional_summary or "").strip(),
        professional_experience=_experience_from_roles(analysis.work_experience_roles),
        education=_education_from_text(analysis.education or ""),
        technical_skills=_skills_from_section(analysis.skills or ""),
        certifications=certs,
        languages=langs,
        additional_info=additional,
        meta=ResumeMeta(
            source_format=source_format,
            source_filename=filename or "",
            normalized_by="heuristic",
        ),
    )


async def ingest_resume(data: bytes, *, filename: str) -> ResumeModel:
    if not data:
        raise ValueError("Resume file is empty.")
    source_format = detect_source_format(data, filename)
    raw_text = extract_text_from_bytes(filename or f"resume.{source_format}", data)
    if not raw_text.strip():
        raise ValueError("Could not extract any text from the uploaded resume.")

    model = build_heuristic_model(
        data, filename=filename, source_format=source_format, raw_text=raw_text
    )

    try:
        from app.services.resume_ingest_ai import normalize_resume_model_with_ai

        normalized, applied = await normalize_resume_model_with_ai(raw_text, model)
        if applied:
            model = normalized
    except Exception:
        logger.exception("AI resume normalization failed; keeping heuristic model")

    if not model.location.strip():
        model.location = guess_candidate_location(raw_text)
    model.meta.source_format = source_format
    model.meta.source_filename = filename or ""
    return model
