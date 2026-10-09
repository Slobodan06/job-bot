"""Applications-per-day for the Team applications chart (pure, unit-testable).

A job counts on the day it was *applied* — ``submitted_at`` — falling back to
when it was added to the tracker (``created_at``) for entries without one.
Days are calendar days in the viewer's own time zone, so an application sent at
11 pm isn't shown on the next day.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ALLOWED_RANGES = (7, 14, 30, 90)
TOP_MEMBERS_PER_DAY = 5


def resolve_tz(name: str | None) -> tzinfo:
    try:
        return ZoneInfo((name or "").strip()) if name and name.strip() else UTC
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    # Mongo hands back naive datetimes that are UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def applied_at(doc: dict[str, Any]) -> datetime | None:
    return _aware(doc.get("submitted_at")) or _aware(doc.get("created_at"))


def local_today(tz: tzinfo, now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(tz).date()


def day_bounds_utc(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """[start, end) of a local calendar day, in UTC."""
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return start.astimezone(UTC), end.astimezone(UTC)


def applied_between_filter(start_utc: datetime, end_utc: datetime) -> dict[str, Any]:
    """Mongo filter: applied (submitted, else added) within [start, end)."""
    window = {"$gte": start_utc, "$lt": end_utc}
    return {
        "$or": [
            {"submitted_at": window},
            {"submitted_at": None, "created_at": window},
        ]
    }


def parse_day(value: str) -> date:
    return date.fromisoformat(value.strip())


def bucket_by_day(
    docs: Iterable[dict[str, Any]],
    *,
    tz: tzinfo,
    first_day: date,
    days: int,
    member_names: dict[Any, str],
) -> list[dict[str, Any]]:
    """One entry per day (including empty days), oldest first, with each day's top members."""
    counts: Counter[date] = Counter()
    per_member: dict[date, Counter[Any]] = defaultdict(Counter)
    last_day = first_day + timedelta(days=days - 1)
    for doc in docs:
        when = applied_at(doc)
        if when is None:
            continue
        day = when.astimezone(tz).date()
        if not first_day <= day <= last_day:
            continue
        counts[day] += 1
        per_member[day][doc.get("user_id")] += 1

    out = []
    for i in range(days):
        day = first_day + timedelta(days=i)
        top = per_member[day].most_common(TOP_MEMBERS_PER_DAY)
        out.append(
            {
                "date": day.isoformat(),
                "count": counts[day],
                "members": [
                    {"id": str(uid), "name": member_names.get(uid) or "(deleted member)", "count": n}
                    for uid, n in top
                ],
            }
        )
    return out
