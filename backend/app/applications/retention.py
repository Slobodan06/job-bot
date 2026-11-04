"""Tracked applications are kept for one month after they were applied, then deleted
together with their saved resume files.

"Applied" is ``submitted_at``, falling back to when the job was added to the tracker
(``created_at``), as everywhere else (see ``daily.applied_at``). The sweep runs at
startup and every few hours; with several workers each sweeps, which is harmless.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from app.applications import service
from app.database import get_db

log = logging.getLogger(__name__)

# 0 or less turns the cleanup off.
RETENTION_DAYS = int(os.getenv("APPLICATION_RETENTION_DAYS", "30"))
SWEEP_INTERVAL_SECONDS = 6 * 60 * 60


def expired_filter(now: datetime, days: int = RETENTION_DAYS) -> dict[str, Any]:
    """Mongo filter: applied (submitted, else added) more than `days` days before `now`."""
    cutoff = now - timedelta(days=days)
    return {
        "$or": [
            {"submitted_at": {"$lt": cutoff}},
            {"submitted_at": None, "created_at": {"$lt": cutoff}},
        ]
    }


async def purge_expired_applications(now: datetime | None = None, days: int = RETENTION_DAYS) -> int:
    """Delete every application past the retention period, with its resume files."""
    if days <= 0:
        return 0
    deleted = 0
    cursor = get_db().applications.find(expired_filter(now or datetime.now(UTC), days), {"_id": 1, "user_id": 1})
    async for doc in cursor:
        await service.delete(doc)
        deleted += 1
    if deleted:
        log.info("Deleted %d tracked application(s) older than %d days.", deleted, days)
    return deleted


async def run_retention_loop() -> None:
    while True:
        try:
            await purge_expired_applications()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a failed sweep retries on the next round
            log.exception("Application retention sweep failed.")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
