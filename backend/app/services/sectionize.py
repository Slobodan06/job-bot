"""Heuristic split of resume plain text into common sections (PDF extraction is unstructured)."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedResume:
    contact: str
    professional_summary: str
    professional_experience: str
    skills: str
    education: str
    other: str


# (bucket_name, regex matching a short section header line)
_SECTION_HEADERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "professional_summary",
        re.compile(
            r"^(professional\s+)?summary\b|^profile\b|^(career\s+)?profile\b|^objectives?\b|^about\s+me\b|^highlights\b",
            re.I,
        ),
    ),
    (
        "professional_experience",
        re.compile(
            r"^professional\s+work\s+experience\b|^(professional\s+)?(work\s+)?experience\b|^employment(\s+history)?\b|"
            r"^work\s+history\b|^career\s+history\b|^relevant\s+experience\b|^professional\s+background\b|^experience\b$",
            re.I,
        ),
    ),
    (
        "skills",
        re.compile(
            r"^technical\s+skills\b|^core\s+competencies\b|^key\s+skills\b|^skills\b|^expertise\b|^competencies\b|"
            r"^tools\b|^technologies\b",
            re.I,
        ),
    ),
    (
        "education",
        re.compile(
            r"^education\b|^academic\b|^qualifications\b|^certifications?\b|^licenses?\b|^training\b",
            re.I,
        ),
    ),
    (
        "other",
        re.compile(
            r"^projects?\b|^publications?\b|^awards?\b|^volunteer\b|^references?\b|^interests?\b",
            re.I,
        ),
    ),
]


def _match_section_header(line: str) -> str | None:
    s = line.strip()
    if len(s) > 100:
        return None
    for name, pat in _SECTION_HEADERS:
        if pat.search(s):
            return name
    return None


def parse_resume_sections(text: str) -> ParsedResume:
    lines = text.replace("\r\n", "\n").split("\n")
    buckets: dict[str, list[str]] = {
        "contact": [],
        "professional_summary": [],
        "professional_experience": [],
        "skills": [],
        "education": [],
        "other": [],
    }
    current = "contact"
    for line in lines:
        stripped = line.strip()
        if stripped:
            sec = _match_section_header(stripped)
            if sec:
                current = sec
                continue
        buckets[current].append(line)

    def join_bucket(key: str) -> str:
        return "\n".join(buckets[key]).strip()

    contact = join_bucket("contact")
    summary = join_bucket("professional_summary")
    experience = join_bucket("professional_experience")
    skills = join_bucket("skills")
    education = join_bucket("education")
    other = join_bucket("other")

    # If nothing was segmented, keep full body as experience so tailoring still runs.
    if not any([summary, experience, skills, education, other]) and contact:
        experience = contact
        contact = ""

    return ParsedResume(
        contact=contact,
        professional_summary=summary,
        professional_experience=experience,
        skills=skills,
        education=education,
        other=other,
    )
