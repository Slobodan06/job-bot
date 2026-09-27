"""Fetches job postings from free, keyless per-company ATS board APIs — Greenhouse,
Lever, Ashby, and SmartRecruiters each publish their customers' open postings without
requiring an API key, unlike aggregator search APIs (e.g. JSearch). Filtering against
the app's MVP criteria (remote, recent, non-intern, software, non-federal) happens in
app.job_boards.logic — this module only fetches and normalizes.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 20.0
_MAX_SMARTRECRUITERS_PAGES = 5  # bounds payload size for very large boards
_HEADERS = {"User-Agent": "job-bot/1.0 (+https://github.com)"}


def _looks_remote(location: str, title: str) -> bool:
    text = f"{location} {title}"
    if re.search(r"\bhybrid\b", text, re.I):
        return False
    return bool(re.search(r"\bremote\b", text, re.I))


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except ValueError:
        return None


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs):
    try:
        resp = await client.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Job board request failed: %s", exc)
        raise ValueError(
            f"That board couldn't be reached ({exc.response.status_code}). "
            "Double-check the company name in the URL."
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Job board request failed: %s", exc)
        raise ValueError("Could not reach the job board. Try again shortly.") from exc


async def _fetch_greenhouse(client: httpx.AsyncClient, token: str) -> tuple[list[dict], str]:
    data = await _get_json(client, f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    raw = data.get("jobs") or []
    company = (raw[0].get("company_name") if raw else "") or token.replace("-", " ").title()
    jobs = []
    for j in raw:
        location = (j.get("location") or {}).get("name") or ""
        title = j.get("title") or ""
        jobs.append(
            {
                "title": title,
                "company": j.get("company_name") or company,
                "location": location,
                "url": j.get("absolute_url") or "",
                "remote": _looks_remote(location, title),
                "employment_type": "",
                "posted_at": _parse_iso(j.get("first_published") or j.get("updated_at")),
                "description_snippet": "",
            }
        )
    return jobs, company


async def _fetch_lever(client: httpx.AsyncClient, token: str) -> tuple[list[dict], str]:
    raw = await _get_json(
        client, f"https://api.lever.co/v0/postings/{token}", params={"mode": "json"}
    )
    company = token.replace("-", " ").title()
    jobs = []
    for j in raw or []:
        categories = j.get("categories") or {}
        location = categories.get("location") or ""
        title = j.get("text") or ""
        workplace_type = (j.get("workplaceType") or "").lower()
        posted_ms = j.get("createdAt")
        posted_at = (
            datetime.fromtimestamp(posted_ms / 1000, tz=UTC)
            if isinstance(posted_ms, (int, float))
            else None
        )
        jobs.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "url": j.get("hostedUrl") or j.get("applyUrl") or "",
                "remote": workplace_type == "remote" or _looks_remote(location, title),
                "employment_type": categories.get("commitment") or "",
                "posted_at": posted_at,
                "description_snippet": (j.get("descriptionPlain") or "").strip()[:280],
            }
        )
    return jobs, company


async def _fetch_ashby(client: httpx.AsyncClient, token: str) -> tuple[list[dict], str]:
    data = await _get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    raw = data.get("jobs") or []
    company = token.replace("-", " ").title()
    jobs = []
    for j in raw:
        if j.get("isListed") is False:
            continue
        location = j.get("location") or ""
        title = j.get("title") or ""
        jobs.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "url": j.get("jobUrl") or j.get("applyUrl") or "",
                "remote": bool(j.get("isRemote")) or _looks_remote(location, title),
                "employment_type": j.get("employmentType") or "",
                "posted_at": _parse_iso(j.get("publishedAt")),
                "description_snippet": (j.get("descriptionPlain") or "").strip()[:280],
            }
        )
    return jobs, company


async def _fetch_smartrecruiters(client: httpx.AsyncClient, token: str) -> tuple[list[dict], str]:
    jobs: list[dict] = []
    company = token.replace("-", " ").title()
    offset = 0
    limit = 100
    for _ in range(_MAX_SMARTRECRUITERS_PAGES):
        data = await _get_json(
            client,
            f"https://api.smartrecruiters.com/v1/companies/{token}/postings",
            params={"offset": offset, "limit": limit},
        )
        content = data.get("content") or []
        if not content:
            break
        for j in content:
            comp = j.get("company") or {}
            company = comp.get("name") or company
            company_identifier = comp.get("identifier") or token
            loc = j.get("location") or {}
            location = loc.get("fullLocation") or loc.get("city") or ""
            title = j.get("name") or ""
            jobs.append(
                {
                    "title": title,
                    "company": company,
                    "location": location,
                    "url": f"https://jobs.smartrecruiters.com/{company_identifier}/{j.get('id')}",
                    "remote": bool(loc.get("remote")) or _looks_remote(location, title),
                    "employment_type": (j.get("typeOfEmployment") or {}).get("label") or "",
                    "posted_at": _parse_iso(j.get("releasedDate")),
                    "description_snippet": "",
                }
            )
        offset += limit
        if offset >= (data.get("totalFound") or 0):
            break
    return jobs, company


async def _fetch_ziprecruiter(client: httpx.AsyncClient, api_key: str) -> tuple[list[dict], str]:
    """Best-effort integration against ZipRecruiter's Jobs Search API.

    UNVERIFIED against a live key — their docs page (ziprecruiter.com/partner/documentation)
    blocks automated fetches with a 403 and we don't hold a ZipRecruiter key to test against,
    unlike every other fetcher in this file (all confirmed live). This follows their
    historically documented Publisher Jobs API v1 shape (GET with `api_key` as a query param).
    If ZipRecruiter has since moved to Basic-auth-header partner API or changed field names,
    this will surface as a clear "couldn't be reached" error rather than fail silently — check
    the response shape against current docs and adjust the field mapping below if it errors.
    """
    params = {
        "search": "software engineer",
        "remote": "only",
        "days_ago": "1",
        "jobs_per_page": "100",
        "api_key": api_key,
    }
    data = await _get_json(client, "https://api.ziprecruiter.com/jobs/v1", params=params)
    raw = data.get("jobs") or []
    jobs = []
    for j in raw:
        title = j.get("name") or j.get("title") or ""
        company = (j.get("hiring_company") or {}).get("name") or j.get("company") or ""
        location = j.get("location") or ""
        jobs.append(
            {
                "title": title,
                "company": company,
                "location": location,
                "url": j.get("url") or "",
                "remote": _looks_remote(location, title) or j.get("remote") in (True, "true", "only"),
                "employment_type": j.get("employment_type") or "",
                "posted_at": _parse_iso(j.get("posted_time")),
                "description_snippet": (j.get("snippet") or j.get("description") or "").strip()[:280],
            }
        )
    return jobs, "ZipRecruiter"


_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
    "smartrecruiters": _fetch_smartrecruiters,
}

_KEYED_FETCHERS = {
    "ziprecruiter": _fetch_ziprecruiter,
}


async def fetch_board_jobs(platform: str, token: str) -> tuple[list[dict], str]:
    """Returns (normalized_jobs, company_display_name). Raises ValueError on failure."""
    fetcher = _FETCHERS.get(platform)
    if fetcher is None:
        raise ValueError(f"Unsupported platform: {platform}")
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        return await fetcher(client, token)


async def fetch_keyed_platform_jobs(platform: str, api_key: str) -> tuple[list[dict], str]:
    """Returns (normalized_jobs, company_display_name) for a platform that needs an
    admin-supplied API key (see app.job_boards.logic.KEYED_PLATFORMS)."""
    fetcher = _KEYED_FETCHERS.get(platform)
    if fetcher is None:
        raise ValueError(f"Unsupported platform: {platform}")
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
        return await fetcher(client, api_key)
