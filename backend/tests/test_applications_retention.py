"""Tracked applications are deleted a month after they were applied, with their resumes."""
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.applications import retention

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def __aiter__(self):
        self._it = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class RetentionTests(unittest.IsolatedAsyncioTestCase):
    def test_filter_uses_applied_date_30_days_back(self) -> None:
        f = retention.expired_filter(NOW, 30)
        cutoff = datetime(2026, 10, 5, 12, tzinfo=UTC)
        self.assertEqual({"$lt": cutoff}, f["$or"][0]["submitted_at"])
        self.assertEqual({"submitted_at": None, "created_at": {"$lt": cutoff}}, f["$or"][1])

    async def test_each_expired_application_is_deleted_with_its_resume(self) -> None:
        docs = [{"_id": 1, "user_id": "u"}, {"_id": 2, "user_id": "u"}]
        db = MagicMock()
        db.applications.find.return_value = _Cursor(docs)
        delete = AsyncMock()
        with patch.object(retention, "get_db", return_value=db), patch.object(retention.service, "delete", delete):
            self.assertEqual(2, await retention.purge_expired_applications(NOW, 30))
        self.assertEqual([d for d in docs], [c.args[0] for c in delete.await_args_list])

    async def test_zero_days_turns_cleanup_off(self) -> None:
        with patch.object(retention, "get_db") as get_db:
            self.assertEqual(0, await retention.purge_expired_applications(NOW, 0))
        get_db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
