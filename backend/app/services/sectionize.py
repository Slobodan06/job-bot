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
            r"^(professional\s+)?summary\b|^profile\b|^(career\s+)?profile\b|^objectives?\b|"
            r"^about(\s+me)?\s*:?\s*$|^highlights\b",
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
            r"^education\b|^academic\b|^qualifications\b|^training\b",
            re.I,
        ),
    ),
    (
        "other",
        re.compile(
            r"^(personal|side|selected|key)\s+projects?\s*:?\s*$|^projects?\s*:?\s*$|"
            r"^publications?\s*:?\s*$|^awards?\s*:?\s*$|^achievements?\s*:?\s*$|"
            r"^volunteer(\s+experience)?\s*:?\s*$|^references?\s*:?\s*$|"
            r"^interests?\s*:?\s*$|^languages?\s*:?\s*$|"
            r"^certifications?\s*:?\s*$|^certification\s*:?\s*$|^certificates?\s*:?\s*$|^licenses?\s*:?\s*$|^courses?\s*:?\s*$|"
            r"^activities\s*:?\s*$|^extracurricular\s*:?\s*$|"
            r"^additional(\s+information|\s+details|\s+experience|\s+strengths)?\s*:?\s*$|"
            r"^hobbies\s*:?\s*$|"
            r"^portfolio\s*:?\s*$",
            re.I,
        ),
    ),
]

_OTHER_TAIL_IN_EDUCATION_RE = re.compile(
    r"^additional\s+strengths\b|^certifications?\s*:?\s*$|^certification\s*:?\s*$|^licenses?\s*:?\s*$|"
    r"^professional\s+certifications?\s*:?\s*$|"
    r"^[-•*–—]\s*.*\bcertificat",
    re.I,
)
_EDU_DEGREE_RE = re.compile(
    r"\b(bachelor|master|doctor|ph\.?\s*d|b\.?\s*s|b\.?\s*a|m\.?\s*s|m\.?\s*a|"
    r"associate|diploma|degree|computer science|licenciatura|grado)\b",
    re.I,
)
_EDU_DATE_RE = re.compile(
    r"(\d{1,2}/\d{4}|\d{4})\s*[–\-—|/to]+\s*(\d{1,2}/\d{4}|\d{4}|present|current)",
    re.I,
)
_MISPLACED_JOB_TITLE_RE = re.compile(
    r"\b(developer|engineer|manager|lead|specialist|architect|consultant|analyst|"
    r"director|coordinator|head|principal|automation)\b",
    re.I,
)
_BULLET_RE = re.compile(r"^[\-\u2022\u25cf\u25cb\u25aa\u25e6*•·]\s*")


def _is_misplaced_job_title_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or _EDU_DEGREE_RE.search(stripped) or _EDU_DATE_RE.search(stripped):
        return False
    if stripped.endswith(".") or len(stripped) > 100:
        return False
    return bool(_MISPLACED_JOB_TITLE_RE.search(stripped))


def _is_education_location_line(line: str) -> bool:
    stripped = line.strip().rstrip(",")
    if _EDU_DATE_RE.search(stripped) or _EDU_DEGREE_RE.search(stripped):
        return False
    if len(stripped) > 48:
        return False
    if re.match(r"^[A-Za-zÀ-ÿ0-9\s.'-]+,\s*[A-Za-zÀ-ÿ0-9\s.'-]+$", stripped):
        return True
    return bool(re.match(r"^(United States|United State|USA|US|U\.S\.?)$", stripped, re.I))


def _orphan_job_insert_indices(lines: list[str], pair_count: int) -> list[int]:
    """Insert misplaced job headers before the first bullet after each date block (skip the first date)."""
    if pair_count <= 0:
        return []
    date_indices = [i for i, line in enumerate(lines) if _EDU_DATE_RE.search(line.strip())]
    if len(date_indices) < 2:
        return []
    target_dates = date_indices[1 : 1 + pair_count]
    if len(target_dates) < pair_count:
        target_dates = date_indices[-pair_count:]
    insert_points: list[int] = []
    for date_idx in target_dates[:pair_count]:
        j = date_idx + 1
        while j < len(lines):
            line = lines[j].strip()
            if _BULLET_RE.match(line):
                insert_points.append(j)
                break
            if _is_misplaced_job_title_line(line):
                break
            j += 1
    return insert_points


def _separate_misplaced_jobs_from_education(education: str, experience: str) -> tuple[str, str]:
    """Two-column PDFs often dump job titles into the education bucket — move them back."""
    if not education.strip():
        return education, experience
    lines = [line.strip() for line in education.splitlines() if line.strip()]
    degree_idx = next((i for i, line in enumerate(lines) if _EDU_DEGREE_RE.search(line)), None)
    if degree_idx is None:
        return education, experience

    prefix = lines[:degree_idx]
    suffix = lines[degree_idx:]
    edu_meta: list[str] = []
    job_lines: list[str] = []
    i = 0
    while i < len(prefix):
        line = prefix[i]
        if _is_misplaced_job_title_line(line):
            job_lines.append(line)
            if (
                i + 1 < len(prefix)
                and not _is_misplaced_job_title_line(prefix[i + 1])
                and not _EDU_DATE_RE.search(prefix[i + 1])
                and not _EDU_DEGREE_RE.search(prefix[i + 1])
                and len(prefix[i + 1]) < 90
                and not prefix[i + 1].endswith(".")
            ):
                job_lines.append(prefix[i + 1])
                i += 2
            else:
                i += 1
        elif line.rstrip().endswith(",") and i + 1 < len(prefix):
            nxt = prefix[i + 1]
            if not _is_misplaced_job_title_line(nxt):
                edu_meta.append(f"{line.rstrip(',')} {nxt}".strip())
                i += 2
            else:
                i += 1
        elif _EDU_DATE_RE.search(line) or _is_education_location_line(line):
            edu_meta.append(line)
            i += 1
        else:
            i += 1

    clean_education = "\n".join([*edu_meta, *suffix]).strip()
    if not job_lines:
        return clean_education, experience

    pairs: list[list[str]] = []
    i = 0
    while i < len(job_lines):
        if i + 1 < len(job_lines):
            pairs.append([job_lines[i], job_lines[i + 1]])
            i += 2
        else:
            pairs.append([job_lines[i]])
            i += 1

    exp_lines = [line for line in experience.splitlines() if line.strip()]
    insert_points = _orphan_job_insert_indices(exp_lines, len(pairs))
    for pair, insert_idx in zip(reversed(pairs), reversed(insert_points)):
        exp_lines.insert(insert_idx, "\n".join(pair))
    merged_experience = "\n".join(exp_lines).strip()
    return clean_education, merged_experience


def _partition_education_and_other(education: str, other: str) -> tuple[str, str]:
    """Move certifications / additional-strengths tail out of the education bucket."""
    if not education.strip():
        return education, other
    lines = education.splitlines()
    split_at: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and _OTHER_TAIL_IN_EDUCATION_RE.match(stripped):
            split_at = i
            break
    if split_at is None:
        return education, other
    edu = "\n".join(lines[:split_at]).strip()
    tail = "\n".join(lines[split_at:]).strip()
    other_parts = [part for part in (tail, other.strip()) if part]
    return edu, "\n\n".join(other_parts)


def _match_section_header(line: str, *, in_contact: bool = False) -> str | None:
    s = line.strip()
    if len(s) > 80:
        return None
    if s.startswith(("-", "•", "*", "–", "—")):
        return None
    words = s.split()
    if len(words) > 6:
        return None
    if s.endswith(".") and len(words) > 3:
        return None
    for name, pat in _SECTION_HEADERS:
        if pat.search(s):
            if in_contact and name == "other":
                continue
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
            sec = _match_section_header(stripped, in_contact=(current == "contact"))
            if sec:
                current = sec
                if sec == "other":
                    buckets[current].append(line)
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

    education, other = _partition_education_and_other(education, other)
    education, experience = _separate_misplaced_jobs_from_education(education, experience)

    return ParsedResume(
        contact=contact,
        professional_summary=summary,
        professional_experience=experience,
        skills=skills,
        education=education,
        other=other,
    )
