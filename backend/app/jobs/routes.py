from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_builder_user
from app.jobs.schemas import JobListing, JobSearchResponse
from app.services.job_search import search_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/search", response_model=JobSearchResponse)
async def search(
    keyword: str = Query(..., min_length=2, max_length=200),
    country: str = Query(default="us", min_length=2, max_length=2),
    remote: bool = Query(default=True),
    posted_within_days: int = Query(default=1, ge=1, le=30),
    page: int = Query(default=1, ge=1, le=10),
    _user: dict = Depends(get_builder_user),
) -> JobSearchResponse:
    try:
        jobs = await search_jobs(
            keyword=keyword,
            country=country,
            remote_only=remote,
            posted_within_days=posted_within_days,
            page=page,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    items = [JobListing(**j) for j in jobs]
    return JobSearchResponse(items=items, count=len(items))
