import unittest
from datetime import UTC, date, datetime

from app.applications.daily import (
    applied_at,
    bucket_by_day,
    day_bounds_utc,
    local_today,
    resolve_tz,
)


class DailyBucketingTests(unittest.TestCase):
    def test_resolve_tz_falls_back_to_utc(self) -> None:
        self.assertEqual("Europe/Belgrade", resolve_tz("Europe/Belgrade").key)
        self.assertIs(UTC, resolve_tz("Not/AZone"))
        self.assertIs(UTC, resolve_tz(None))

    def test_applied_at_prefers_submitted_then_created(self) -> None:
        sub = datetime(2026, 10, 1, 9, 0)
        created = datetime(2026, 9, 30, 9, 0)
        self.assertEqual(sub.replace(tzinfo=UTC), applied_at({"submitted_at": sub, "created_at": created}))
        self.assertEqual(created.replace(tzinfo=UTC), applied_at({"submitted_at": None, "created_at": created}))
        self.assertIsNone(applied_at({}))

    def test_late_evening_counts_on_the_local_day(self) -> None:
        tz = resolve_tz("America/New_York")
        # 23:30 New York on Oct 7 is 03:30 UTC on Oct 8.
        docs = [{"user_id": "a", "submitted_at": datetime(2026, 10, 8, 3, 30)}]
        days = bucket_by_day(docs, tz=tz, first_day=date(2026, 10, 7), days=2, member_names={"a": "Ana"})
        self.assertEqual([("2026-10-07", 1), ("2026-10-08", 0)], [(d["date"], d["count"]) for d in days])

    def test_empty_days_included_and_top_members_ranked(self) -> None:
        docs = [
            {"user_id": "a", "submitted_at": datetime(2026, 10, 1, 10)},
            {"user_id": "b", "submitted_at": datetime(2026, 10, 1, 11)},
            {"user_id": "b", "submitted_at": datetime(2026, 10, 1, 12)},
            {"user_id": "a", "submitted_at": datetime(2026, 10, 3, 12)},
            {"user_id": "a", "submitted_at": datetime(2026, 9, 1, 12)},  # outside the window
        ]
        days = bucket_by_day(
            docs, tz=UTC, first_day=date(2026, 10, 1), days=3, member_names={"a": "Ana", "b": "Ben"}
        )
        self.assertEqual([3, 0, 1], [d["count"] for d in days])
        self.assertEqual([("Ben", 2), ("Ana", 1)], [(m["name"], m["count"]) for m in days[0]["members"]])
        self.assertEqual([], days[1]["members"])

    def test_day_bounds_and_today_follow_the_zone(self) -> None:
        tz = resolve_tz("Europe/Belgrade")  # UTC+2 in October (DST)
        start, end = day_bounds_utc(date(2026, 10, 8), tz)
        self.assertEqual(datetime(2026, 10, 7, 22, tzinfo=UTC), start)
        self.assertEqual(datetime(2026, 10, 8, 22, tzinfo=UTC), end)
        self.assertEqual(date(2026, 10, 9), local_today(tz, now=datetime(2026, 10, 8, 23, tzinfo=UTC)))


if __name__ == "__main__":
    unittest.main()
