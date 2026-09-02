"""Canonical normalized resume model.

Every uploaded resume (``.docx``, ``.pdf`` or legacy ``.doc``) is converted once
into a :class:`ResumeModel`. Tailoring and both renderers (RenderCV PDF, DOCX)
consume this structure directly, so no layout-specific string re-parsing happens
at render time. The string adapters exist only for the evidence/validation
machinery in :mod:`app.services.resume_evidence` and :mod:`app.services.tailor`,
which are still text oriented, and for the RenderCV-failure fallback renderer.

The JSON shape mirrors the structure product/design signed off on:

    {
      "name": "...", "title": "...", "location": "...",
      "contact": {"email","phone","linkedin","github","website"},
      "professional_summary": "...",
      "professional_experience": [{"title","company","dates","location","responsibilities":[]}],
      "education": [{"degree","field","school","duration"}],
      "technical_skills": {"Frontend": [...], "Backend & API": [...]},
      "certifications": [], "languages": [], "additional_info": [],
      "meta": {...}   # internal tracking only
    }
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.services.resume_sections import WorkExperienceRole

_BULLET_PREFIX_RE = re.compile(r"^[\-*•●○▪◦·∙]+\s*")
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


class ResumeContact(BaseModel):
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""


class ResumeExperienceEntry(BaseModel):
    title: str = ""
    company: str = ""
    dates: str = ""          # verbatim source range, e.g. "March 2024 – May 2026"
    location: str = ""       # this job's own location, e.g. "Brea, CA"
    responsibilities: list[str] = Field(default_factory=list)


class ResumeEducationEntry(BaseModel):
    degree: str = ""
    field: str = ""
    school: str = ""
    duration: str = ""


class ResumeMeta(BaseModel):
    source_format: str = "docx"  # docx | pdf | doc
    source_filename: str = ""
    normalized_by: str = "heuristic"  # ai | heuristic
    warnings: list[str] = Field(default_factory=list)


class ResumeModel(BaseModel):
    name: str = ""
    title: str = ""
    location: str = ""  # the candidate's own city/region from the resume header
    contact: ResumeContact = Field(default_factory=ResumeContact)
    professional_summary: str = ""
    professional_experience: list[ResumeExperienceEntry] = Field(default_factory=list)
    education: list[ResumeEducationEntry] = Field(default_factory=list)
    technical_skills: dict[str, list[str]] = Field(default_factory=dict)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    additional_info: list[str] = Field(default_factory=list)
    meta: ResumeMeta = Field(default_factory=ResumeMeta)

    # ---- string adapters (for the text-oriented evidence/tailor machinery) ----

    def contact_block(self) -> str:
        lines: list[str] = []
        if self.name:
            lines.append(self.name)
        if self.title:
            lines.append(self.title)
        detail = " | ".join(v for v in (self.contact.email, self.contact.phone, self.location) if v)
        if detail:
            lines.append(detail)
        for url in (self.contact.linkedin, self.contact.github, self.contact.website):
            if url:
                lines.append(url)
        return "\n".join(lines).strip()

    def summary_text(self) -> str:
        return (self.professional_summary or "").strip()

    def skills_text(self) -> str:
        return skills_dict_to_text(self.technical_skills)

    def experience_text(self) -> str:
        blocks: list[str] = []
        for role in self.professional_experience:
            header = " | ".join(
                part for part in (role.company, role.title, role.location, role.dates) if part
            )
            lines = [header] if header else []
            lines.extend(f"- {b.strip()}" for b in role.responsibilities if b.strip())
            if lines:
                blocks.append("\n".join(lines))
        return "\n\n".join(blocks).strip()

    def education_text(self) -> str:
        blocks: list[str] = []
        for entry in self.education:
            detail = " in ".join(p for p in (entry.degree, entry.field) if p) if entry.degree else entry.field
            lines = [part for part in (entry.school, detail, entry.duration) if part]
            if lines:
                blocks.append("\n".join(lines))
        return "\n\n".join(blocks).strip()

    def extra_sections(self) -> list[tuple[str, list[str]]]:
        out: list[tuple[str, list[str]]] = []
        if self.certifications:
            out.append(("Certifications", list(self.certifications)))
        if self.languages:
            out.append(("Languages", list(self.languages)))
        if self.additional_info:
            out.append(("Additional Information", list(self.additional_info)))
        return out

    def extras_text(self) -> str:
        blocks: list[str] = []
        for heading, entries in self.extra_sections():
            clean = [e.strip() for e in entries if e.strip()]
            if clean:
                blocks.append("\n".join([heading.upper(), *(f"- {e}" for e in clean)]))
        return "\n\n".join(blocks).strip()

    def work_experience_roles(self) -> list[WorkExperienceRole]:
        roles: list[WorkExperienceRole] = []
        for role in self.professional_experience:
            header = " | ".join(
                part for part in (role.company, role.title, role.location, role.dates) if part
            )
            roles.append(
                WorkExperienceRole(
                    header=header or role.title or role.company,
                    company=role.company,
                    title=role.title,
                    location=role.location,
                    period=role.dates,
                    bullets=tuple(b.strip() for b in role.responsibilities if b.strip()),
                )
            )
        return roles


# ---------------------------------------------------------------------------
# skill helpers
# ---------------------------------------------------------------------------


def skills_dict_to_text(skills: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for category, items in (skills or {}).items():
        clean = ", ".join(item.strip() for item in items if item and item.strip())
        if not clean:
            continue
        label = (category or "").strip()
        lines.append(f"{label}: {clean}" if label else f"Skills: {clean}")
    return "\n".join(lines).strip()


def skills_dict_from_text(skills_text: str) -> dict[str, list[str]]:
    """Parse ``Category: a, b`` lines (the LLM / skill-audit format) into a dict."""
    out: dict[str, list[str]] = {}
    pending_label = ""
    for raw_line in (skills_text or "").splitlines():
        line = _BULLET_PREFIX_RE.sub("", raw_line).strip()
        if not line:
            continue
        if ":" in line:
            label, _, details = line.partition(":")
            label = label.strip()
            items = _split_skill_items(details)
            if label and items:
                out.setdefault(label, [])
                out[label].extend(i for i in items if i not in out[label])
                pending_label = ""
                continue
            if label and not items:
                pending_label = label
                continue
        label = pending_label or "Skills"
        pending_label = ""
        out.setdefault(label, [])
        out[label].extend(i for i in _split_skill_items(line) if i not in out[label])
    return {k: v for k, v in out.items() if v}


def _split_skill_items(value: str) -> list[str]:
    out: list[str] = []
    for token in re.split(r"[,;|/•]+", value or ""):
        token = token.strip(" .–—-")
        if token and len(token) > 1 and token.lower() not in {t.lower() for t in out}:
            out.append(token)
    return out


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------


def normalize_date_token(raw: str) -> str:
    """Return ``MM/YYYY`` / ``YYYY`` / ``Present`` for a single date token."""
    text = (raw or "").strip().strip(".,")
    if not text:
        return ""
    if re.search(r"\b(present|current|now|ongoing|till date|to date)\b", text, re.I):
        return "Present"
    m = re.search(r"\b(0?[1-9]|1[0-2])\s*[/\-.]\s*((?:19|20)\d{2})\b", text)
    if m:
        return f"{int(m.group(1)):02d}/{m.group(2)}"
    m = re.search(r"\b((?:19|20)\d{2})\s*[/\-.]\s*(0?[1-9]|1[0-2])\b", text)
    if m:
        return f"{int(m.group(2)):02d}/{m.group(1)}"
    m = re.search(r"([A-Za-z]{3,9})\.?\s+((?:19|20)\d{2})", text)
    if m:
        name = m.group(1).lower()
        month = _MONTHS.get(name[:4]) or _MONTHS.get(name[:3])
        if month:
            return f"{month:02d}/{m.group(2)}"
    m = re.search(r"\b((?:19|20)\d{2})\b", text)
    if m:
        return m.group(1)
    return ""


def split_date_range(date_text: str) -> tuple[str, str]:
    """Split ``Jan 2020 - Present`` style ranges into normalized (start, end)."""
    text = (date_text or "").strip()
    if not text:
        return "", ""
    parts = re.split(r"\s*[–—\-]{1,2}\s*|\s+(?:to|until)\s+", text, maxsplit=1, flags=re.I)
    if len(parts) == 2:
        return normalize_date_token(parts[0]), normalize_date_token(parts[1])
    single = normalize_date_token(text)
    return (single, "") if single and single != "Present" else ("", single)
