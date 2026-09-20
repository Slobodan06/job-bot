from datetime import datetime

from pydantic import BaseModel


class JobListing(BaseModel):
    title: str
    company: str
    location: str
    url: str
    source: str
    remote: bool
    employment_type: str
    posted_at: datetime | None = None
    description_snippet: str


class JobSearchResponse(BaseModel):
    items: list[JobListing]
    count: int
