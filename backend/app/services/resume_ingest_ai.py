"""AI normalization pass that turns a heuristic resume draft into a clean model.

This is strict extraction, never resume writing: the model may re-slot, split
combined lines, assign bullets to the right employer and tidy formatting, but it
must not invent employers, titles, skills, links, or accomplishments. Every fixed
field the model returns is validated against the raw document text; anything not
source-backed falls back to the deterministic heuristic draft.
"""
from __future__ import annotations

import json
import logging
import os
import re

from openai import AsyncOpenAI

from app.services.openai_compat import chat_completion_controls
from app.services.resume_analysis_ai import _json_object
from app.services.resume_model import (
    ResumeContact,
    ResumeEducationEntry,
    ResumeExperienceEntry,
    ResumeModel,
)

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You normalize noisy resume extraction into a strict JSON structure. "
    "This is extraction, not resume writing. Never invent or infer an employer, "
    "job title, date, location, skill, link, degree, or accomplishment. Copy "
    "every fact verbatim from the source text. You may split combined lines, "
    "move a line to the correct section, attach each bullet to the employer it "
    "belongs to, and group skills under their real category headings. Return "
    "strict JSON only."
)

_SCHEMA_HINT = """Return JSON with exactly this shape:
{
  "name": "", "title": "", "location": "",
  "contact": {"email": "", "phone": "", "linkedin": "", "github": "", "website": ""},
  "professional_summary": "",
  "professional_experience": [
    {"title": "", "company": "", "dates": "", "location": "", "responsibilities": ["", ""]}
  ],
  "education": [{"degree": "", "field": "", "school": "", "duration": ""}],
  "technical_skills": {"Category Name": ["skill", "skill"]},
  "certifications": [], "languages": [], "additional_info": ["", ""]
}
Rules:
- "title" (top level) is the candidate's professional role / target job title
  (for example "Senior Software Engineer"). It is NEVER a city, region, country,
  or company name. Leave it "" if the resume header has no such title.
- "location" (top level) is the CANDIDATE'S OWN city/region from the resume header
  (for example "Duncan, South Carolina, United States"). It is NOT an employer city.
- Each professional_experience entry's "location" is THAT JOB'S city, copied from
  the source. Leave it "" when the source does not state a location for that job.
  Never copy the candidate's header location into a job, and never swap job locations.
- "dates" is the job's date range copied verbatim (e.g. "March 2024 - May 2026").
- Keep responsibility wording as written in the source; do not rewrite or embellish.
- Only include a skill if the exact token appears in the source text.
- Preserve employer order as in the source (usually newest first)."""


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold().replace("–", "-").replace("—", "-")).strip()


def _phrase_in_source(value: str, source_norm: str) -> bool:
    v = _norm(value)
    return bool(v) and v in source_norm


def _mostly_in_source(text: str, source_norm: str, threshold: float = 0.55) -> bool:
    tokens = re.findall(r"[a-z0-9][a-z0-9+#.\-]{2,}", _norm(text))
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in source_norm)
    return hits / len(tokens) >= threshold


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _backed(value: object, fallback: str, source_norm: str) -> str:
    text = str(value or "").strip()
    return text if text and _phrase_in_source(text, source_norm) else fallback


def _validated_location(value: object, fallback: str, source_norm: str) -> str:
    text = str(value or "").strip()
    if text and _mostly_in_source(text, source_norm, threshold=0.5):
        return text
    return fallback


_TITLE_ROLE_RE = re.compile(
    r"\b(engineer|developer|manager|architect|consultant|analyst|designer|specialist|"
    r"lead|principal|scientist|programmer|administrator|director|coordinator|intern|"
    r"founder|owner|head|officer|stack|frontend|backend|devops|sre)\b",
    re.I,
)


def _validated_title(value: object, fallback: str, source_norm: str, location: str) -> str:
    text = str(value or "").strip()
    if not text or not _phrase_in_source(text, source_norm):
        return fallback if not _looks_like_location(fallback, location) else ""
    if _looks_like_location(text, location):
        return ""
    return text


def _looks_like_location(text: str, location: str) -> bool:
    text = (text or "").strip()
    if not text or _TITLE_ROLE_RE.search(text):
        return False
    loc = (location or "").casefold()
    if loc and (text.casefold() == loc or text.casefold() in loc):
        return True
    return bool(re.fullmatch(r"[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*)*(?:,\s*[\w.'-]+(?:\s+[\w.'-]+)*){1,3}", text))


def _validated_contact(raw: dict, draft: ResumeContact, source_norm: str, source_raw: str) -> ResumeContact:
    email = str(raw.get("email") or "").strip()
    if email.casefold() not in source_norm:
        email = draft.email
    phone = str(raw.get("phone") or "").strip()
    if not (_digits(phone) and _digits(phone) in _digits(source_raw)):
        phone = draft.phone

    def link(name: str, fallback: str) -> str:
        url = str(raw.get(name) or "").strip()
        bare = url.lower().replace("https://", "").replace("http://", "").rstrip("/")
        haystack = source_raw.lower().replace("https://", "").replace("http://", "")
        return url if bare and bare in haystack else fallback

    return ResumeContact(
        email=email,
        phone=phone,
        linkedin=link("linkedin", draft.linkedin),
        github=link("github", draft.github),
        website=link("website", draft.website),
    )


def _validated_experience(raw_list, draft: list[ResumeExperienceEntry], source_norm: str) -> list[ResumeExperienceEntry]:
    if not isinstance(raw_list, list) or not raw_list:
        return draft
    out: list[ResumeExperienceEntry] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            continue
        fb = draft[i] if i < len(draft) else ResumeExperienceEntry()
        responsibilities = [
            str(b).strip()
            for b in (item.get("responsibilities") or [])
            if str(b).strip() and _mostly_in_source(str(b), source_norm)
        ] or list(fb.responsibilities)
        company = _backed(item.get("company"), fb.company, source_norm)
        title = _backed(item.get("title"), fb.title, source_norm)
        if not company and not title and not responsibilities:
            continue
        out.append(
            ResumeExperienceEntry(
                title=title,
                company=company,
                dates=_backed(item.get("dates"), fb.dates, source_norm),
                location=_backed(item.get("location"), fb.location, source_norm),
                responsibilities=responsibilities,
            )
        )
    return out or draft


def _validated_education(raw_list, draft: list[ResumeEducationEntry], source_norm: str) -> list[ResumeEducationEntry]:
    if not isinstance(raw_list, list) or not raw_list:
        return draft
    out: list[ResumeEducationEntry] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            continue
        fb = draft[i] if i < len(draft) else ResumeEducationEntry()
        school = _backed(item.get("school"), fb.school, source_norm)
        field = _backed(item.get("field"), fb.field, source_norm)
        if not school and not field:
            continue
        out.append(
            ResumeEducationEntry(
                degree=_backed(item.get("degree"), fb.degree, source_norm),
                field=field,
                school=school,
                duration=_backed(item.get("duration"), fb.duration, source_norm),
            )
        )
    return out or draft


def _validated_skills(raw_map, draft: dict[str, list[str]], source_norm: str) -> dict[str, list[str]]:
    if not isinstance(raw_map, dict) or not raw_map:
        return draft
    out: dict[str, list[str]] = {}
    for category, items in raw_map.items():
        if not isinstance(items, list):
            continue
        kept = [
            s
            for s in (str(x).strip() for x in items)
            if s and _phrase_in_source(s, source_norm)
        ]
        if kept:
            out[str(category).strip() or "Skills"] = kept
    return out or draft


def _validated_list(raw_list, draft: list[str], source_norm: str) -> list[str]:
    if not isinstance(raw_list, list):
        return draft
    kept = [
        str(x).strip()
        for x in raw_list
        if str(x).strip() and _mostly_in_source(str(x), source_norm, threshold=0.5)
    ]
    return kept or draft


async def normalize_resume_model_with_ai(raw_text: str, draft: ResumeModel) -> tuple[ResumeModel, bool]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or not raw_text.strip():
        return draft, False

    model_name = (
        os.getenv("OPENAI_MODEL_ANALYSIS", "").strip()
        or os.getenv("OPENAI_MODEL_FAST", "").strip()
        or "gpt-4o-mini"
    )
    draft_json = draft.model_dump(exclude={"meta"})
    prompt = (
        f"SOURCE RESUME TEXT:\n{raw_text[:40000]}\n\n"
        f"HEURISTIC DRAFT (fix mistakes, do not add facts):\n"
        f"{json.dumps(draft_json, ensure_ascii=False)[:14000]}\n\n"
        f"{_SCHEMA_HINT}"
    )
    try:
        timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "120") or "120")
        client = AsyncOpenAI(api_key=api_key, timeout=max(30.0, min(timeout, 300.0)))
        completion = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            **chat_completion_controls(model_name, max_output_tokens=6000, temperature=0),
        )
        payload = _json_object(completion.choices[0].message.content or "")
    except Exception:
        logger.exception("AI resume normalization request failed")
        return draft, False

    if not payload:
        return draft, False

    source_norm = _norm(raw_text)
    raw_contact = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    summary = str(payload.get("professional_summary") or "").strip()
    if not summary or not _mostly_in_source(summary, source_norm, threshold=0.45):
        summary = draft.professional_summary

    location = _validated_location(payload.get("location"), draft.location, source_norm)
    normalized = ResumeModel(
        name=_backed(payload.get("name"), draft.name, source_norm) or draft.name,
        title=_validated_title(payload.get("title"), draft.title, source_norm, location),
        location=location,
        contact=_validated_contact(raw_contact, draft.contact, source_norm, raw_text),
        professional_summary=summary,
        professional_experience=_validated_experience(
            payload.get("professional_experience"), draft.professional_experience, source_norm
        ),
        education=_validated_education(payload.get("education"), draft.education, source_norm),
        technical_skills=_validated_skills(
            payload.get("technical_skills"), draft.technical_skills, source_norm
        ),
        certifications=_validated_list(payload.get("certifications"), draft.certifications, source_norm),
        languages=_validated_list(payload.get("languages"), draft.languages, source_norm),
        additional_info=_validated_list(payload.get("additional_info"), draft.additional_info, source_norm),
        meta=draft.meta.model_copy(update={"normalized_by": "ai"}),
    )
    if not normalized.professional_experience:
        normalized.professional_experience = draft.professional_experience
    return normalized, True
