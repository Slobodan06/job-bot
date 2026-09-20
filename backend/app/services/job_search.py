"""Live job search against the JSearch API (RapidAPI), which aggregates postings
from Google for Jobs, LinkedIn, Indeed, and other boards.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import httpx

logger = logging.getLogger(__name__)

_JSEARCH_HOST = "jsearch.p.rapidapi.com"
# JSearch's RapidAPI listing serves search under /search-v2 (the old /search path 404s);
# it also ignores remote_jobs_only, so "remote" is folded into the query text instead
# and cross-checked against job_is_remote after the fact.
_JSEARCH_URL = f"https://{_JSEARCH_HOST}/search-v2"


def _date_posted_param(days: int) -> str:
    if days <= 1:
        return "today"
    if days <= 3:
        return "3days"
    if days <= 7:
        return "week"
    return "month"


def _normalize(job: dict) -> dict:
    posted_ts = job.get("job_posted_at_timestamp")
    posted_at = None
    if isinstance(posted_ts, (int, float)):
        posted_at = datetime.fromtimestamp(posted_ts, tz=UTC).isoformat()

    is_remote = bool(job.get("job_is_remote"))
    parts = [p for p in (job.get("job_city"), job.get("job_state"), job.get("job_country")) if p]
    location = "Remote" if is_remote and not parts else ", ".join(parts)

    return {
        "title": job.get("job_title") or "",
        "company": job.get("employer_name") or "",
        "location": location,
        "url": job.get("job_apply_link") or job.get("job_google_link") or "",
        "source": job.get("job_publisher") or "",
        "remote": is_remote,
        "employment_type": job.get("job_employment_type") or "",
        "posted_at": posted_at,
        "description_snippet": (job.get("job_description") or "").strip()[:280],
    }


async def search_jobs(
    *,
    keyword: str,
    country: str = "us",
    remote_only: bool = True,
    posted_within_days: int = 1,
    page: int = 1,
) -> list[dict]:
    api_key = os.getenv("RAPIDAPI_KEY", "").strip()
    if not api_key:
        raise ValueError("Job search is not configured. Set RAPIDAPI_KEY in backend/.env.")

    keyword = keyword.strip()
    if not keyword:
        raise ValueError("Enter a keyword to search for.")
    query = f"{keyword} remote" if remote_only else keyword

    params = {
        "query": query,
        "page": str(page),
        "num_pages": "1",
        "date_posted": _date_posted_param(posted_within_days),
        "country": (country or "us").strip().lower(),
    }
    headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": _JSEARCH_HOST}

    resp: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=25.0) as client:
        for attempt in range(2):
            try:
                resp = await client.get(_JSEARCH_URL, params=params, headers=headers)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                logger.warning("JSearch request failed: %s", exc)
                raise ValueError(
                    f"Job search provider returned an error ({exc.response.status_code})."
                ) from exc
            except httpx.HTTPError as exc:
                logger.warning("JSearch request failed (attempt %d): %s", attempt + 1, exc)
                if attempt == 1:
                    raise ValueError(
                        "Could not reach the job search provider. Try again shortly."
                    ) from exc
    assert resp is not None

    payload = resp.json()
    raw_jobs = ((payload.get("data") or {}).get("jobs")) or []
    jobs = [_normalize(job) for job in raw_jobs]
    if remote_only:
        jobs = [j for j in jobs if j["remote"]]
    jobs.sort(key=lambda j: j["posted_at"] or "", reverse=True)
    return jobs
