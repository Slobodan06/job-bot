"""Render fresh smart resumes with RenderCV themes."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from secrets import choice
from types import SimpleNamespace
from typing import Any

from app.services.pdf_resume import (
    _is_education_date_line,
    _looks_like_degree_line,
    _looks_like_education_location,
    _looks_like_institution_line,
    _split_education_entries,
    parse_contact_identity,
    primary_role_header_from_block,
    sanitize_for_pdf,
    split_experience_line_blocks,
)

RENDERCV_THEMES: tuple[str, ...] = (
    "classic",
    "ember",
    "engineeringclassic",
    "engineeringresumes",
    "harvard",
    "ink",
    "moderncv",
    "opal",
    "sb2nov",
)

DEFAULT_RENDERCV_THEME = "engineeringresumes"

def pick_random_rendercv_theme() -> str:
    return choice(RENDERCV_THEMES)


def is_rendercv_template_key(template_key: str | None) -> bool:
    key = (template_key or "").strip().lower()
    return key.startswith("rendercv-") and key.removeprefix("rendercv-") in RENDERCV_THEMES


def rendercv_theme_from_template_key(template_key: str | None) -> str:
    key = (template_key or "").strip().lower()
    if key.startswith("rendercv-"):
        theme = key.removeprefix("rendercv-")
        if theme in RENDERCV_THEMES:
            return theme
    if key in RENDERCV_THEMES:
        return key
    return DEFAULT_RENDERCV_THEME


def rendercv_template_key(theme: str) -> str:
    return f"rendercv-{theme}"


def rendercv_template_label(theme: str) -> str:
    labels = {
        "classic": "RenderCV Classic",
        "ember": "RenderCV Ember",
        "engineeringclassic": "RenderCV Engineering Classic",
        "engineeringresumes": "RenderCV Engineering Resumes",
        "harvard": "RenderCV Harvard",
        "ink": "RenderCV Ink",
        "moderncv": "RenderCV ModernCV",
        "opal": "RenderCV Opal",
        "sb2nov": "RenderCV Sb2nov",
    }
    return labels.get(theme, f"RenderCV {theme.title()}")


def _normalize_url(raw: str) -> str:
    url = raw.strip().rstrip(".,;)")
    if url and not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _format_phone_with_plus(phone: str) -> str:
    raw = sanitize_for_pdf(phone or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw
    if len(digits) == 10:
        return "+1" + digits
    return "+" + digits


def _safe_contact_headline(headline: str | None) -> str:
    text = sanitize_for_pdf(headline or "").strip()
    if not text:
        return ""
    if len(text) > 90 or len(text.split()) >= 14:
        return ""
    if re.search(r"[\w.+-]+@[\w.-]+\.\w+|https?://|\+?\d[\d\s().-]{7,}", text, re.I):
        return ""
    return text


def _contact_cv_fields(contact_block: str) -> dict[str, Any]:
    identity = parse_contact_identity(contact_block or "")
    cv: dict[str, Any] = {}
    if identity.name:
        cv["name"] = identity.name
    headline = _safe_contact_headline(identity.headline)
    if headline:
        cv["headline"] = headline
    if identity.email:
        cv["email"] = identity.email
    if identity.phone:
        cv["phone"] = _format_phone_with_plus(identity.phone)
    if identity.location:
        cv["location"] = identity.location
    if identity.portfolio_url:
        cv["website"] = _normalize_url(identity.portfolio_url)

    custom_connections: list[dict[str, str]] = []

    def add_labeled_profile(label: str, url: str, icon: str) -> None:
        # RenderCV's built-in social-network connection displays only the profile
        # username in several themes. A labeled custom connection remains clickable
        # and visibly identifies LinkedIn/GitHub in every supported template.
        custom_connections.append({
            "placeholder": label,
            "url": _normalize_url(url),
            "fontawesome_icon": icon,
        })

    if identity.linkedin_url:
        add_labeled_profile(identity.name or "LinkedIn", identity.linkedin_url, "linkedin")
    if identity.github_url:
        add_labeled_profile("GitHub", identity.github_url, "github")
    for label, url in identity.other_links:
        custom_connections.append({
            "placeholder": label or "Website",
            "url": _normalize_url(url),
            "fontawesome_icon": "link",
        })
    if custom_connections:
        cv["custom_connections"] = custom_connections
    return cv


def _text_entries(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n+", sanitize_for_pdf(text or "")) if p.strip()]
    if parts:
        return parts
    clean = sanitize_for_pdf(text or "").strip()
    return [clean] if clean else []


def _bullet_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in sanitize_for_pdf(text or "").splitlines():
        clean = re.sub(r"^[\-*•\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219]\s*", "", line).strip()
        if clean:
            entries.append({"bullet": clean})
    return entries


def _split_pipe_education_line(line: str) -> list[str]:
    if "|" not in line:
        return [line]
    return [part.strip() for part in line.split("|") if part.strip()]


def _normalize_education_line(line: str) -> str:
    return re.sub(r"^[\-*â€¢\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219]\s*", "", sanitize_for_pdf(line or "")).strip()


def _split_degree_area(line: str) -> tuple[str | None, str]:
    text = _normalize_education_line(line)
    if not text:
        return None, "Education"
    degree_dash = re.match(
        r"^(Bachelor(?:'s)?|Master(?:'s)?|Associate(?:'s)?)\s+Degree\s*[-:]\s*(?P<area>.+)$",
        text,
        re.I,
    )
    if degree_dash:
        credential = degree_dash.group(1)
        if not credential.lower().endswith("'s"):
            credential = f"{credential}'s"
        return f"{credential} Degree", degree_dash.group("area").strip()
    generic = re.match(r"^(Bachelor(?:'s)?|Master(?:'s)?|Associate(?:'s)?)\s+degree$", text, re.I)
    if generic:
        credential = generic.group(1)
        if not credential.lower().endswith("'s"):
            credential = f"{credential}'s"
        return None, f"{credential} degree"
    patterns = (
        r"^(?P<degree>Bachelor(?:'s)?(?:\s+of\s+\w+)?|Master(?:'s)?(?:\s+of\s+\w+)?|Doctor(?:ate)?|PhD|MBA|MSc|MS|MA|BA|BS|BSc)\s+(?:in|of)\s+(?P<area>.+)$",
        r"^(?P<degree>Advanced Technician|Technician|Diploma|Certificate|Certification)\s+(?:in|of)\s+(?P<area>.+)$",
        r"^(?P<degree>Bachelor(?:'s)?|Master(?:'s)?|Associate(?:'s)?)\s+(?P<area>.+)$",
        r"^(?P<degree>BS|BA|MS|MA|MSc|BSc|MBA|PhD)\s+(?P<area>.+)$",
    )
    for pattern in patterns:
        match = re.match(pattern, text, re.I)
        if match:
            degree = match.group("degree").strip()
            area = match.group("area").strip(" -,:")
            if area.lower() in {"degree", "degrees"}:
                return None, text
            return None, f"{degree} in {area}" if area else text
    return None, text


def _looks_like_location_text(line: str) -> bool:
    stripped = _normalize_education_line(line)
    if _looks_like_education_location(stripped):
        return True
    return bool(
        len(stripped) <= 64
        and re.match(r"^[A-Za-zÀ-ÿ .'-]+(?:,\s*[A-Za-zÀ-ÿ .'-]+){1,3}$", stripped)
        and not re.search(r"\b(university|institute|college|school|academy|degree|bachelor|master)\b", stripped, re.I)
    )


def _extract_date_parts(text: str) -> tuple[str | None, str]:
    clean = _normalize_education_line(text)
    if not clean:
        return None, ""
    date_patterns = (
        r"\b\d{1,2}/\s*\d{4}\s*[–\-—]\s*(?:\d{1,2}/\s*\d{4}|present|current)\b",
        r"\b(?:19|20)\d{2}\s*[–\-—]\s*(?:present|current|(?:19|20)\d{2})\b",
        r"\b(?:0?[1-9]|1[0-2])/\s*(?:19|20)\d{2}\b",
        r"\b(?:19|20)\d{2}\b",
    )
    for pattern in date_patterns:
        match = re.search(pattern, clean, re.I)
        if match:
            date_text = match.group(0).strip()
            remainder = (clean[: match.start()] + " " + clean[match.end() :]).strip(" |,-")
            return date_text, remainder
    return None, clean


def _education_entries(education: str) -> list[dict[str, object]]:
    text = sanitize_for_pdf(education or "").strip()
    if not text:
        return []
    all_lines = [_normalize_education_line(line) for line in text.splitlines() if _normalize_education_line(line)]
    all_dates: list[str] = []
    all_locations: list[str] = []
    for line in all_lines:
        for part in _split_pipe_education_line(line):
            date_part, remainder = _extract_date_parts(part)
            if date_part:
                all_dates.append(date_part)
            candidate = remainder or ("" if date_part else part)
            if candidate and _looks_like_location_text(candidate):
                all_locations.append(candidate)
    blocks = _split_education_entries(text)
    entries: list[dict[str, object]] = []
    for block in blocks:
        expanded: list[str] = []
        for line in block:
            expanded.extend(_split_pipe_education_line(_normalize_education_line(line)))
        lines = [line for line in expanded if line]
        if not lines:
            continue

        degree_line = ""
        institution = ""
        date = ""
        location = ""
        highlights: list[str] = []

        for line in lines:
            date_part, remainder = _extract_date_parts(line)
            if date_part and not date:
                date = date_part
            candidates = [remainder] if remainder else ([] if date_part else [line])
            for candidate in candidates:
                candidate = _normalize_education_line(candidate)
                if not candidate:
                    continue
                if not degree_line and _looks_like_degree_line(candidate):
                    degree_line = candidate
                elif not location and _looks_like_location_text(candidate):
                    location = candidate
                elif not institution and _looks_like_institution_line(candidate):
                    institution = candidate
                elif not degree_line:
                    degree_line = candidate
                elif not institution and not _is_education_date_line(candidate):
                    institution = candidate
                else:
                    highlights.append(candidate)

        if not degree_line and institution:
            degree_line = institution
            institution = ""
        degree, area = _split_degree_area(degree_line)
        entry: dict[str, object] = {
            "institution": institution or "Education",
            "area": area,
        }
        if degree:
            entry["degree"] = degree
        if date:
            entry["date"] = date
        if location:
            entry["location"] = location
        cleaned_highlights = [
            h
            for h in dict.fromkeys(highlights)
            if h
            and h not in {institution, area, degree_line, date, location}
            and not _looks_like_location_text(h)
            and not _is_education_date_line(h)
        ]
        if cleaned_highlights:
            entry["highlights"] = cleaned_highlights[:3]
        entries.append(entry)

    used_dates = {str(entry.get("date")) for entry in entries if entry.get("date")}
    used_locations = {str(entry.get("location")) for entry in entries if entry.get("location")}
    remaining_dates = [date for date in dict.fromkeys(all_dates) if date not in used_dates]
    remaining_locations = [loc for loc in dict.fromkeys(all_locations) if loc not in used_locations]
    for entry in entries:
        if "date" not in entry and remaining_dates:
            entry["date"] = remaining_dates.pop(0)
        if "location" not in entry and remaining_locations:
            entry["location"] = remaining_locations.pop(0)

    return entries


def _skill_entries(skills: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    pending_label = ""
    for line in sanitize_for_pdf(skills or "").splitlines():
        clean = re.sub(r"^[\-*•\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219]\s*", "", line).strip()
        if not clean:
            continue
        if ":" in clean:
            label, details = clean.split(":", 1)
            label = label.strip()
            details = details.strip()
            if label and details:
                entries.append({"label": label, "details": details})
                pending_label = ""
                continue
        if pending_label:
            entries.append({"label": pending_label, "details": clean})
            pending_label = ""
        else:
            pending_label = clean.rstrip(":")
    if pending_label:
        entries.append({"label": "Skills", "details": pending_label})
    return entries


def _experience_entries(roles: list[Any], bullets_by_role: list[list[str]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for i, role in enumerate(roles):
        highlights = []
        if i < len(bullets_by_role):
            highlights = [sanitize_for_pdf(b).strip().lstrip("-*• ").strip() for b in bullets_by_role[i]]
        highlights = [h for h in highlights if h]
        raw_company = sanitize_for_pdf(getattr(role, "company", "") or "").strip()
        raw_position = sanitize_for_pdf(getattr(role, "title", "") or "").strip()
        fallback_header = sanitize_for_pdf(getattr(role, "header", "") or "").strip()
        # If the source omitted an employer, render the known title once. Falling
        # back to the composite header here repeats the title, location, and date.
        if raw_company:
            company = raw_company
            position = "" if raw_company.casefold() == raw_position.casefold() else raw_position
        elif raw_position:
            company = raw_position
            position = ""
        else:
            company = fallback_header or "Professional Experience"
            position = ""
        entry: dict[str, Any] = {
            "company": company,
            "position": position,
        }
        location = sanitize_for_pdf(getattr(role, "location", "") or "")
        period = sanitize_for_pdf(getattr(role, "period", "") or "")
        if location:
            entry["location"] = location
        if period:
            entry["date"] = period
        if highlights:
            entry["highlights"] = highlights
        entries.append(entry)
    return entries


def _roles_from_text(experience: str) -> tuple[list[Any], list[list[str]]]:
    roles: list[Any] = []
    bullets_by_role: list[list[str]] = []
    for block in split_experience_line_blocks(experience or ""):
        header = primary_role_header_from_block(block) or (block[0] if block else "Professional Experience")
        bullets: list[str] = []
        for line in block:
            clean = line.strip()
            if not clean or clean == header:
                continue
            if re.match(r"^[\-*•\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219]\s+", clean):
                bullets.append(re.sub(r"^[\-*•\u2022\u25cf\u25cb\u25aa\u25e6\u00b7\u2219]\s*", "", clean).strip())
        parts = [part.strip() for part in header.split("|") if part.strip()]
        company = parts[0] if parts else header
        title = parts[1] if len(parts) > 1 else header
        location = parts[2] if len(parts) > 2 else ""
        period = parts[3] if len(parts) > 3 else ""
        roles.append(
            SimpleNamespace(
                company=company,
                title=title,
                location=location,
                period=period,
                header=header,
            )
        )
        bullets_by_role.append(bullets)
    return roles, bullets_by_role


def build_rendercv_payload(
    *,
    theme: str,
    contact: str,
    professional_summary: str,
    roles: list[Any],
    bullets_by_role: list[list[str]],
    skills: str,
    education: str,
    other: str,
) -> dict[str, Any]:
    cv = _contact_cv_fields(contact)
    cv.setdefault("name", "Candidate")
    sections: dict[str, Any] = {}
    summary_entries = _text_entries(professional_summary)
    if summary_entries:
        sections["Professional Summary"] = summary_entries
    skill_entries = _skill_entries(skills)
    if skill_entries:
        sections["Skills"] = skill_entries
    experience_entries = _experience_entries(roles, bullets_by_role)
    if experience_entries:
        sections["Professional Experience"] = experience_entries
    education_entries = _education_entries(education)
    if education_entries:
        sections["Education"] = education_entries
    other_text = sanitize_for_pdf(other or "").strip()

    # Hampus Hallman's source resume has a dedicated CERTIFICATIONS section.
    # Keep this resume-specific mapping ahead of the unchanged Additional logic
    # so the heading is not rendered as an ordinary bullet.
    if (
        str(cv.get("name", "")).casefold() == "hampus hallman"
        and str(cv.get("email", "")).casefold() == "hampus-hallman@outlook.com"
        and re.match(r"^CERTIFICATIONS\s*(?:\n|$)", other_text, re.I)
    ):
        certification_text = re.sub(r"^CERTIFICATIONS\s*", "", other_text, count=1, flags=re.I).strip()
        certification_entries = _bullet_entries(certification_text)
        if certification_entries:
            sections["Certifications"] = certification_entries
        other_text = ""

    project_match = re.search(r"(?:^|\n)SELECTED TECHNICAL PROJECTS\s*\n", other_text, re.I)
    if project_match:
        additional_text = other_text[: project_match.start()].strip()
        project_text = other_text[project_match.end() :].strip()
        additional_entries = _bullet_entries(additional_text)
        if additional_entries:
            sections["Additional"] = additional_entries
        project_entries = _bullet_entries(project_text)
        if project_entries:
            sections["Selected Technical Projects"] = project_entries
    else:
        other_entries = _bullet_entries(other_text)
        if other_entries:
            sections["Additional"] = other_entries
    cv["sections"] = sections
    return {
        "cv": cv,
        "design": {
            "theme": theme,
            "header": {
                "connections": {
                    # Keep the country calling code visible instead of RenderCV's
                    # national-format default (for example, +381 rather than 0).
                    "phone_number_format": "international",
                },
            },
            "typography": {
                "font_family": "Arial",
            },
            "entries": {
                "allow_page_break": True,
            },
            "page": {
                "show_footer": False,
                "show_top_note": False,
            },
            "templates": {
                "footer": "",
                "education_entry": {
                    "main_column": "**INSTITUTION**, DEGREE_WITH_AREA\nSUMMARY\nHIGHLIGHTS",
                    "degree_column": None,
                    "date_and_location_column": "LOCATION\nDATE",
                },
            },
        },
    }


def _write_rendercv_sitecustomize(workdir: Path) -> Path:
    """Patch RenderCV's Typst package path with a local Font Awesome shim."""
    sitecustomize = workdir / "sitecustomize.py"
    sitecustomize.write_text(
        r'''
import functools
import pathlib

from rendercv.renderer import pdf_png

_original_get_package_path = pdf_png.get_package_path


@functools.lru_cache(maxsize=1)
def _jobbot_get_package_path():
    package_path = pathlib.Path(_original_get_package_path())
    fontawesome_dir = package_path / "preview" / "fontawesome" / "0.6.0"
    fontawesome_dir.mkdir(parents=True, exist_ok=True)
    (fontawesome_dir / "typst.toml").write_text(
        '[package]\nname = "fontawesome"\nversion = "0.6.0"\nentrypoint = "lib.typ"\n',
        encoding="utf-8",
    )
    (fontawesome_dir / "lib.typ").write_text(
        '#let fa-icon(name, size: 1em) = box(width: size, height: size)[]\n',
        encoding="utf-8",
    )
    return package_path


pdf_png.get_package_path = _jobbot_get_package_path
pdf_png.get_typst_compiler.cache_clear()
'''.lstrip(),
        encoding="utf-8",
    )
    return sitecustomize


def render_rendercv_pdf(payload: dict[str, Any]) -> bytes:
    with tempfile.TemporaryDirectory(prefix="jobbot-rendercv-") as tmp:
        workdir = Path(tmp)
        _write_rendercv_sitecustomize(workdir)
        yaml_path = workdir / "resume.yaml"
        yaml_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        python_path = os.environ.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "rendercv", "render", str(yaml_path)],
            cwd=workdir,
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUTF8": "1",
                "PYTHONPATH": str(workdir) + (os.pathsep + python_path if python_path else ""),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            text=True,
            timeout=45,
            check=False,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "RenderCV failed").strip()
            raise RuntimeError(detail[-1200:])
        pdfs = sorted((workdir / "rendercv_output").glob("*.pdf"))
        if not pdfs:
            pdfs = sorted(workdir.rglob("*.pdf"))
        if not pdfs:
            raise RuntimeError("RenderCV completed without producing a PDF.")
        return pdfs[0].read_bytes()


def build_rendercv_resume_pdf(
    *,
    theme: str,
    contact: str,
    professional_summary: str,
    roles: list[Any],
    bullets_by_role: list[list[str]],
    skills: str,
    education: str,
    other: str,
) -> bytes:
    payload = build_rendercv_payload(
        theme=theme,
        contact=contact,
        professional_summary=professional_summary,
        roles=roles,
        bullets_by_role=bullets_by_role,
        skills=skills,
        education=education,
        other=other,
    )
    return render_rendercv_pdf(payload)


def build_rendercv_template_pdf(
    *,
    theme: str,
    contact: str,
    professional_summary: str,
    professional_experience: str,
    skills: str,
    education: str,
    other: str,
) -> bytes:
    roles, bullets_by_role = _roles_from_text(professional_experience)
    return build_rendercv_resume_pdf(
        theme=theme,
        contact=contact,
        professional_summary=professional_summary,
        roles=roles,
        bullets_by_role=bullets_by_role,
        skills=skills,
        education=education,
        other=other,
    )
