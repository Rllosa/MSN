"""Daily auto-archive worker.

Runs once per day at midnight UTC.  Archives:
- Beds24 (Airbnb/Booking.com) conversations where checkout_date < today - 7 days
- WhatsApp and email conversations where last_message_at < now - 15 days

Only conversations with unread_count = 0 are archived (safety guard).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db.session import worker_session

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None

_SQL_ARCHIVE_STALE_BEDS24 = text(
    "UPDATE conversations"
    " SET status = 'archived', updated_at = NOW()"
    " WHERE status = 'active'"
    "   AND unread_count = 0"
    "   AND platform IN ('airbnb', 'booking')"
    "   AND checkout_date IS NOT NULL"
    "   AND checkout_date < CURRENT_DATE - INTERVAL '7 days'"
)

_SQL_ARCHIVE_INACTIVE = text(
    "UPDATE conversations"
    " SET status = 'archived', updated_at = NOW()"
    " WHERE status = 'active'"
    "   AND unread_count = 0"
    "   AND platform NOT IN ('airbnb', 'booking')"
    "   AND last_message_at < NOW() - INTERVAL '15 days'"
)


async def _run_archive_worker() -> None:
    while True:
        # Sleep until next midnight UTC
        now = datetime.now(UTC)
        tomorrow_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep((tomorrow_midnight - now).total_seconds())

        try:
            async with worker_session() as session:
                r1 = await session.execute(_SQL_ARCHIVE_STALE_BEDS24)
                r2 = await session.execute(_SQL_ARCHIVE_INACTIVE)
                await session.commit()
                logger.info(
                    "archive.worker.ran beds24=%d inactive=%d",
                    r1.rowcount,
                    r2.rowcount,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("archive.worker.error")


def start_archive_worker() -> None:
    global _worker_task
    _worker_task = asyncio.create_task(_run_archive_worker(), name="archive_worker")


async def stop_archive_worker() -> None:
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _worker_task
        _worker_task = None
