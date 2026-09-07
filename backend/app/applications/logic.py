"""Pure helpers for the job-application tracker (no DB, unit-testable)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

# Ordered application pipeline. `detected` is created by the extension the moment
# a posting is recognised; the rest are user/observed transitions.
APPLICATION_STATUSES: tuple[str, ...] = (
    "detected",
    "drafting",
    "ready",
    "submitted",
    "interviewing",
    "offer",
    "rejected",
    "withdrawn",
)

_ATS_HOST_RE = (
    (re.compile(r"(?:^|\.)greenhouse\.io$|(?:^|\.)boards\.greenhouse\.io$", re.I), "greenhouse"),
    (re.compile(r"(?:^|\.)lever\.co$", re.I), "lever"),
    (re.compile(r"(?:^|\.)myworkdayjobs\.com$|(?:^|\.)workday\.com$", re.I), "workday"),
    (re.compile(r"(?:^|\.)ashbyhq\.com$", re.I), "ashby"),
    (re.compile(r"(?:^|\.)smartrecruiters\.com$", re.I), "smartrecruiters"),
    (re.compile(r"(?:^|\.)workable\.com$", re.I), "workable"),
    (re.compile(r"(?:^|\.)icims\.com$", re.I), "icims"),
    (re.compile(r"(?:^|\.)bamboohr\.com$", re.I), "bamboohr"),
    (re.compile(r"(?:^|\.)jobvite\.com$", re.I), "jobvite"),
    (re.compile(r"(?:^|\.)breezy\.hr$", re.I), "breezy"),
    (re.compile(r"(?:^|\.)linkedin\.com$", re.I), "linkedin"),
    (re.compile(r"(?:^|\.)indeed\.com$", re.I), "indeed"),
)

# Query keys that identify a specific posting and must survive normalization.
_KEEP_QUERY_KEYS = {"gh_jid", "jobid", "job_id", "id", "lever-source", "jk"}


def detect_ats(url: str) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    for pattern, name in _ATS_HOST_RE:
        if pattern.search(host):
            return name
    return "other"


def normalize_job_url(url: str) -> str:
    """Canonical posting URL: drop scheme case, fragments, tracking params, trailing slash."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if parsed.port and parsed.port not in (80, 443):
        host = f"{host}:{parsed.port}"
    path = re.sub(r"/+$", "", parsed.path) or "/"
    kept = []
    for pair in parsed.query.split("&"):
        if not pair or "=" not in pair:
            continue
        key = pair.split("=", 1)[0].lower()
        if key in _KEEP_QUERY_KEYS:
            kept.append(pair)
    query = "&".join(sorted(kept))
    return urlunparse(("https", host, path, "", query, ""))


def job_hash(url: str) -> str:
    return hashlib.sha1(normalize_job_url(url).encode("utf-8")).hexdigest()


def is_valid_status(value: str) -> bool:
    return value in APPLICATION_STATUSES


def _clip(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def build_application_doc(
    *,
    user_id: Any,
    payload: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Shape an inbound extension payload into a new `applications` document."""
    url = _clip(payload.get("job_url"), 2000)
    status = str(payload.get("status") or "detected")
    if not is_valid_status(status):
        status = "detected"
    return {
        "user_id": user_id,
        "job_hash": job_hash(url),
        "job_url": url,
        "ats": _clip(payload.get("ats"), 32) or detect_ats(url),
        "company": _clip(payload.get("company"), 200),
        "job_title": _clip(payload.get("job_title"), 300),
        "location": _clip(payload.get("location"), 200),
        "jd_text": _clip(payload.get("jd_text"), 40000),
        "status": status,
        "resume_variant_id": None,
        "answers": [],
        "scores": {},
        "notes": "",
        "created_at": now,
        "updated_at": now,
        "submitted_at": now if status == "submitted" else None,
    }


def application_doc_to_public(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(doc["_id"]),
        "job_url": doc.get("job_url") or "",
        "ats": doc.get("ats") or "other",
        "company": doc.get("company") or "",
        "job_title": doc.get("job_title") or "",
        "location": doc.get("location") or "",
        "status": doc.get("status") or "detected",
        "resume_variant_id": (
            str(doc["resume_variant_id"]) if doc.get("resume_variant_id") else None
        ),
        "notes": doc.get("notes") or "",
        "answers": doc.get("answers") or [],
        "scores": doc.get("scores") or {},
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "submitted_at": doc.get("submitted_at"),
    }
