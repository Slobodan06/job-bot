"""The tracker's date filter: local calendar days, inclusive, either end open."""
import unittest
from datetime import UTC, datetime

from app.applications.daily import with_applied_dates


def _window(query: dict) -> dict:
    return query["$and"][-1]["$or"][0]["submitted_at"]


class AppliedDatesTests(unittest.TestCase):
    def test_no_dates_leaves_the_filter_alone(self) -> None:
        self.assertEqual({"user_id": 1}, with_applied_dates({"user_id": 1}))

    def test_range_covers_both_whole_days_in_the_viewers_zone(self) -> None:
        w = _window(with_applied_dates({}, date_from="2026-11-01", date_to="2026-11-02", tz="America/New_York"))
        self.assertEqual(datetime(2026, 11, 1, 4, tzinfo=UTC), w["$gte"])  # midnight EDT
        self.assertEqual(datetime(2026, 11, 3, 5, tzinfo=UTC), w["$lt"])  # midnight EST, after DST ends

    def test_one_day(self) -> None:
        w = _window(with_applied_dates({}, date_from="2026-11-02", date_to="2026-11-02"))
        self.assertEqual((datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 3, tzinfo=UTC)), (w["$gte"], w["$lt"]))

    def test_open_ended_and_reversed_ranges(self) -> None:
        since = _window(with_applied_dates({}, date_from="2026-11-01"))
        self.assertEqual(datetime(2026, 11, 1, tzinfo=UTC), since["$gte"])
        w = _window(with_applied_dates({}, date_from="2026-11-05", date_to="2026-11-01"))
        self.assertEqual((datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 6, tzinfo=UTC)), (w["$gte"], w["$lt"]))

    def test_keeps_the_search_boxs_or(self) -> None:
        q = with_applied_dates({"$or": [{"company": "x"}]}, date_from="2026-11-01")
        self.assertEqual([{"company": "x"}], q["$or"])

    def test_bad_date_raises(self) -> None:
        with self.assertRaises(ValueError):
            with_applied_dates({}, date_from="11/02/2026")


if __name__ == "__main__":
    unittest.main()
