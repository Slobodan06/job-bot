"""Pure helpers for job-board ingestion (no DB, no HTTP — see app.services.job_boards
for the fetchers). Reuses the same URL-hash dedupe primitive as the application tracker
(app.applications.logic) so a posting is recognized as "the same job" the same way
across both features.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from app.applications.logic import detect_ats, job_hash, normalize_job_url

SUPPORTED_BOARD_PLATFORMS = {"greenhouse", "lever", "ashby", "smartrecruiters"}

_BOARD_HOSTS = {
    "greenhouse": "boards.greenhouse.io",
    "lever": "jobs.lever.co",
    "ashby": "jobs.ashbyhq.com",
    "smartrecruiters": "jobs.smartrecruiters.com",
}

# Platforms that have a real jobs API but require a subscriber/publisher API key —
# unlike the free per-company ATS boards above. An admin supplies the key once
# (encrypted at rest); after that these behave like any other tracked source.
KEYED_PLATFORMS: dict[str, dict[str, Any]] = {
    "ziprecruiter": {
        "host_re": re.compile(r"(?:^|\.)ziprecruiter\.com$", re.I),
        "label": "ZipRecruiter",
        "url": "https://www.ziprecruiter.com/",
        # ZipRecruiter's search API ("ZipSearch") isn't self-serve — this is their
        # partner integration portal; getting a key means applying for their
        # Publisher program (reviewed, not instant). No confirmed self-serve signup
        # page as of this writing, so we point to docs plus their integrations
        # contact rather than a guessed "sign up" URL.
        "signup_url": "https://www.ziprecruiter.com/partner/documentation/",
        "signup_note": (
            "No instant self-serve signup — apply to ZipRecruiter's Publisher program "
            "for a ZipSearch API key, or email atsintegrations@ziprecruiter.com."
        ),
    },
}

POSTED_WITHIN_HOURS_DEFAULT = 24


class UnsupportedBoardError(ValueError):
    """Raised when a pasted URL is a platform we can't fetch at all (no free API, no key
    support built yet) — the caller shows this as an alert; scraping would be required.
    """

    def __init__(self, platform: str, host: str):
        self.platform = platform
        self.host = host
        if platform == "other":
            message = (
                f'"{host}" isn\'t a recognized job board platform with an open API '
                "(supported: Greenhouse, Lever, Ashby, SmartRecruiters, ZipRecruiter). "
                "Scraping would be required for this source, which isn't implemented yet."
            )
        else:
            message = (
                f"{platform.title()} boards don't expose an open jobs API we support yet "
                "(supported: Greenhouse, Lever, Ashby, SmartRecruiters, ZipRecruiter). "
                "Scraping would be required for this source, which isn't implemented yet."
            )
        super().__init__(message)


class ApiKeyRequiredError(ValueError):
    """Raised when a pasted URL matches a KEYED_PLATFORMS entry but no key is stored yet.
    The caller surfaces this distinctly (HTTP 428) so the frontend can prompt an admin
    for a key instead of showing a flat "unsupported" alert.
    """

    def __init__(self, platform: str, label: str, signup_url: str, signup_note: str):
        self.platform = platform
        self.label = label
        self.signup_url = signup_url
        self.signup_note = signup_note
        super().__init__(
            f"{label} requires an API key. An admin can add one to enable this source."
        )


def detect_keyed_platform(host: str) -> str | None:
    for platform, meta in KEYED_PLATFORMS.items():
        if meta["host_re"].search(host):
            return platform
    return None


def keyed_platform_url(platform: str) -> str:
    return KEYED_PLATFORMS[platform]["url"]


def keyed_platform_label(platform: str) -> str:
    return KEYED_PLATFORMS[platform]["label"]


def keyed_platform_signup_url(platform: str) -> str:
    return KEYED_PLATFORMS[platform].get("signup_url", "")


def keyed_platform_signup_note(platform: str) -> str:
    return KEYED_PLATFORMS[platform].get("signup_note", "")


def parse_board_url(url: str) -> tuple[str, str]:
    """Returns (platform, company_token) for a free, keyless ATS board.
    Raises ApiKeyRequiredError for a recognized-but-keyed platform (caller decides
    whether a key is already on file), UnsupportedBoardError for anything else
    unrecognized, or ValueError for a malformed/empty input.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("Paste a job board URL first.")
    normalized = raw if re.match(r"^https?://", raw, re.I) else f"https://{raw}"
    parsed = urlparse(normalized)
    host = parsed.hostname or raw
    platform = detect_ats(normalized)
    if platform in SUPPORTED_BOARD_PLATFORMS:
        segments = [s for s in parsed.path.split("/") if s]
        if not segments:
            raise ValueError(
                f"Couldn't find a company name in that {platform.title()} URL — paste the "
                f"full board link, e.g. https://{_BOARD_HOSTS[platform]}/yourcompany."
            )
        return platform, segments[0]

    keyed = detect_keyed_platform(host)
    if keyed:
        raise ApiKeyRequiredError(
            keyed,
            keyed_platform_label(keyed),
            keyed_platform_signup_url(keyed),
            keyed_platform_signup_note(keyed),
        )

    raise UnsupportedBoardError(platform, host)


def board_url_for(platform: str, token: str) -> str:
    return f"https://{_BOARD_HOSTS[platform]}/{token}"


_SOFTWARE_INCLUDE_RE = re.compile(
    r"software|developer|programmer|\bsde\b|\bswe\b|full[\s-]?stack|front[\s-]?end|"
    r"back[\s-]?end|devops|site reliability|\bsre\b|machine learning|\bml engineer\b|"
    r"ai engineer|data engineer|platform engineer|cloud engineer|security engineer|"
    r"infrastructure engineer|mobile engineer|ios engineer|android engineer|"
    r"qa engineer|quality engineer|test engineer|systems engineer|network engineer|"
    r"database engineer|application engineer|web developer|\bengineer\b",
    re.IGNORECASE,
)
_SOFTWARE_EXCLUDE_RE = re.compile(
    r"mechanical engineer|civil engineer|chemical engineer|electrical engineer|"
    r"sales engineer|process engineer|manufacturing engineer|field engineer|"
    r"structural engineer|biomedical engineer|petroleum engineer|environmental engineer|"
    r"industrial engineer|\bhvac\b",
    re.IGNORECASE,
)
_INTERN_RE = re.compile(r"\bintern(?:ship)?s?\b|\bco-?op\b|working student", re.IGNORECASE)
_FEDERAL_RE = re.compile(
    r"\bfederal\b|\bclearance\b|\bts/sci\b|\bpublic trust\b|\.gov\b|"
    r"department of defense|\bdod\b|government agency",
    re.IGNORECASE,
)


def is_software_role(title: str) -> bool:
    if _SOFTWARE_EXCLUDE_RE.search(title):
        return False
    return bool(_SOFTWARE_INCLUDE_RE.search(title))


def is_intern_role(title: str, employment_type: str) -> bool:
    return bool(_INTERN_RE.search(title) or _INTERN_RE.search(employment_type))


def is_federal_role(title: str, location: str, company: str) -> bool:
    return bool(_FEDERAL_RE.search(f"{title} {location} {company}"))


def is_recent(posted_at: datetime | None, *, hours: int, now: datetime) -> bool:
    if posted_at is None:
        return False
    return (now - posted_at) <= timedelta(hours=hours)


def passes_filters(job: dict[str, Any], *, now: datetime, hours: int) -> bool:
    """Applies the fixed MVP criteria: remote, posted recently, not an internship,
    software-related, and not a federal/cleared role.
    """
    if not job["remote"]:
        return False
    if not is_recent(job["posted_at"], hours=hours, now=now):
        return False
    if is_intern_role(job["title"], job["employment_type"]):
        return False
    if not is_software_role(job["title"]):
        return False
    if is_federal_role(job["title"], job["location"], job["company"]):
        return False
    return True


def build_job_docs(
    *,
    board_id: Any,
    platform: str,
    raw_jobs: list[dict[str, Any]],
    now: datetime,
    hours: int = POSTED_WITHIN_HOURS_DEFAULT,
) -> tuple[list[dict[str, Any]], int]:
    """Normalize + filter raw platform jobs into sourced_jobs documents.
    Returns (docs, filtered_out_count). These are app-wide, not per-user — only an
    admin adds sources (see get_owner_user in job_boards/routes.py), and everyone on
    the team sees the resulting list. Dedup happens at insert time via the unique
    job_hash index, shared across every tracked board and platform.
    """
    docs = []
    filtered_out = 0
    for job in raw_jobs:
        if not job.get("url") or not job.get("title"):
            filtered_out += 1
            continue
        if not passes_filters(job, now=now, hours=hours):
            filtered_out += 1
            continue
        docs.append(
            {
                "board_id": board_id,
                "job_hash": job_hash(job["url"]),
                "platform": platform,
                "company": job["company"],
                "title": job["title"],
                "location": job["location"],
                "url": normalize_job_url(job["url"]) or job["url"],
                "remote": job["remote"],
                "employment_type": job["employment_type"],
                "posted_at": job["posted_at"],
                "description_snippet": job["description_snippet"],
                "created_at": now,
            }
        )
    return docs, filtered_out


def build_board_doc(
    *,
    added_by: Any,
    platform: str,
    token: str,
    board_url: str,
    company: str,
    now: datetime,
    job_count: int,
) -> dict[str, Any]:
    return {
        "added_by": added_by,
        "platform": platform,
        "token": token,
        "board_url": board_url,
        "company": company,
        "added_at": now,
        "last_synced_at": now,
        "job_count": job_count,
    }


def board_doc_to_public(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "platform": doc.get("platform") or "",
        "company": doc.get("company") or "",
        "board_url": doc.get("board_url") or "",
        "added_at": doc.get("added_at"),
        "last_synced_at": doc.get("last_synced_at"),
        "job_count": doc.get("job_count") or 0,
    }


def job_doc_to_listing(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": doc.get("title") or "",
        "company": doc.get("company") or "",
        "location": doc.get("location") or "",
        "url": doc.get("url") or "",
        "source": doc.get("platform") or "",
        "remote": bool(doc.get("remote")),
        "employment_type": doc.get("employment_type") or "",
        "posted_at": doc.get("posted_at"),
        "description_snippet": doc.get("description_snippet") or "",
    }
