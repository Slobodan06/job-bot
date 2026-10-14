"""Owner report: who uses (spends) the OpenAI credits."""
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth.dependencies import get_owner_user
from app.database import get_db
from app.services.ai_usage import estimate_cost_usd

router = APIRouter(prefix="/api/admin/ai-usage", tags=["admin"])


class FeatureUsage(BaseModel):
    feature: str
    requests: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class MemberUsage(BaseModel):
    member_id: str | None
    name: str = ""
    email: str = ""
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    last_used_at: datetime | None = None
    features: list[FeatureUsage] = Field(default_factory=list)


class DailyUsage(BaseModel):
    date: str
    requests: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class AiUsageReport(BaseModel):
    days: int
    total_requests: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    # Models used in the period with no known price (their cost counts as 0).
    unpriced_models: list[str] = Field(default_factory=list)
    members: list[MemberUsage] = Field(default_factory=list)
    daily: list[DailyUsage] = Field(default_factory=list)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


@router.get("", response_model=AiUsageReport)
async def ai_usage_report(
    days: int = Query(default=30, ge=1, le=365),
    _owner: dict = Depends(get_owner_user),
) -> AiUsageReport:
    db = get_db()
    since = datetime.now(UTC) - timedelta(days=days)
    rows = [
        r
        async for r in db.ai_usage.find(
            {"at": {"$gte": since}},
            {"user_id": 1, "at": 1, "model": 1, "feature": 1, "prompt_tokens": 1,
             "completion_tokens": 1, "total_tokens": 1, "cached_tokens": 1},
        )
    ]

    per_member: dict[Any, dict] = {}
    per_day: dict[str, DailyUsage] = {}
    unpriced: set[str] = set()
    for r in rows:
        uid = r.get("user_id")
        # Re-priced from tokens with the current price table, so a price correction
        # (or OPENAI_PRICING_JSON) also fixes past rows.
        cost = estimate_cost_usd(
            r.get("model") or "",
            r.get("prompt_tokens") or 0,
            r.get("completion_tokens") or 0,
            r.get("cached_tokens") or 0,
        )
        if cost is None:
            unpriced.add(r.get("model") or "unknown")
            cost = 0.0
        m = per_member.setdefault(
            uid,
            {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
             "cost_usd": 0.0, "last_used_at": None, "features": defaultdict(lambda: [0, 0, 0.0])},
        )
        m["requests"] += 1
        m["prompt_tokens"] += r.get("prompt_tokens") or 0
        m["completion_tokens"] += r.get("completion_tokens") or 0
        m["total_tokens"] += r.get("total_tokens") or 0
        m["cost_usd"] += cost
        at = _aware(r.get("at"))
        if at and (m["last_used_at"] is None or at > m["last_used_at"]):
            m["last_used_at"] = at
        f = m["features"][r.get("feature") or "Other"]
        f[0] += 1
        f[1] += r.get("total_tokens") or 0
        f[2] += cost
        if at:
            day = per_day.setdefault(at.date().isoformat(), DailyUsage(date=at.date().isoformat()))
            day.requests += 1
            day.total_tokens += r.get("total_tokens") or 0
            day.cost_usd += cost

    users = {
        u["_id"]: u
        async for u in db.users.find(
            {"_id": {"$in": [uid for uid in per_member if uid is not None]}}, {"name": 1, "email": 1}
        )
    }
    members: list[MemberUsage] = []
    for uid, m in per_member.items():
        user = users.get(uid) or {}
        features = sorted(
            (FeatureUsage(feature=k, requests=v[0], total_tokens=v[1], cost_usd=round(v[2], 4))
             for k, v in m["features"].items()),
            key=lambda f: (f.cost_usd, f.total_tokens),
            reverse=True,
        )
        members.append(
            MemberUsage(
                member_id=str(uid) if uid is not None else None,
                name=user.get("name") or ("Background jobs" if uid is None else "(deleted member)"),
                email=user.get("email") or "",
                requests=m["requests"],
                prompt_tokens=m["prompt_tokens"],
                completion_tokens=m["completion_tokens"],
                total_tokens=m["total_tokens"],
                cost_usd=round(m["cost_usd"], 4),
                last_used_at=m["last_used_at"],
                features=features,
            )
        )
    # Top spenders first (tokens break ties / cover unpriced models).
    members.sort(key=lambda x: (x.cost_usd, x.total_tokens), reverse=True)
    daily = sorted(per_day.values(), key=lambda d: d.date)
    for d in daily:
        d.cost_usd = round(d.cost_usd, 4)
    return AiUsageReport(
        days=days,
        total_requests=sum(m.requests for m in members),
        total_tokens=sum(m.total_tokens for m in members),
        total_cost_usd=round(sum(m.cost_usd for m in members), 4),
        unpriced_models=sorted(unpriced),
        members=members,
        daily=daily,
    )
