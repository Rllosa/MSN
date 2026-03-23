"""Daily auto-archive worker.

Runs once per day at midnight UTC.  Archives:
- Beds24 (Airbnb/Booking.com) conversations where checkout_date < today - 7 days
- Confirmed bookings (checkout_date in the future) silent > 15 days
- Airbnb/Booking inquiries with no checkout_date inactive > 15 days (pre-booking
  inquiries that never converted to a confirmed booking)
- Beds24 conversations whose booking is cancelled in Beds24 API (unread_count = 0)
- WhatsApp and email conversations where last_message_at < now - 15 days

Only conversations with unread_count = 0 are archived (safety guard).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text

from app.db.session import worker_session
from app.workers.beds24 import _load_refresh_token
from app.workers.locks import archive_lock

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

_SQL_ARCHIVE_SILENT_BOOKINGS = text(
    "UPDATE conversations"
    " SET status = 'archived', updated_at = NOW()"
    " WHERE status = 'active'"
    "   AND unread_count = 0"
    "   AND platform IN ('airbnb', 'booking')"
    "   AND checkout_date > CURRENT_DATE"
    "   AND last_message_at < NOW() - INTERVAL '15 days'"
)

_SQL_ARCHIVE_NO_CHECKOUT = text(
    "UPDATE conversations"
    " SET status = 'archived', updated_at = NOW()"
    " WHERE status = 'active'"
    "   AND unread_count = 0"
    "   AND platform IN ('airbnb', 'booking')"
    "   AND checkout_date IS NULL"
    "   AND last_message_at < NOW() - INTERVAL '15 days'"
)

_SQL_ARCHIVE_INACTIVE = text(
    "UPDATE conversations"
    " SET status = 'archived', updated_at = NOW()"
    " WHERE status = 'active'"
    "   AND unread_count = 0"
    "   AND platform NOT IN ('airbnb', 'booking')"
    "   AND last_message_at < NOW() - INTERVAL '15 days'"
)

_SQL_ACTIVE_BOOKING_IDS = text(
    "SELECT id::text, guest_contact FROM conversations"
    " WHERE status = 'active'"
    "   AND platform IN ('airbnb', 'booking')"
    "   AND guest_contact ~ '^[0-9]+$'"
)

_SQL_ARCHIVE_CANCELLED = text(
    "UPDATE conversations SET status = 'archived', updated_at = NOW()"
    " WHERE guest_contact = ANY(:contacts) AND status = 'active' AND unread_count = 0"
)


async def _archive_cancelled_bookings() -> int:
    """Fetch cancelled bookings from Beds24 API and archive matching active
    conversations with unread_count = 0.

    Returns the number of conversations archived.
    """
    from app.clients.beds24 import Beds24Client

    try:
        refresh_token = await _load_refresh_token()
        async with httpx.AsyncClient() as http:
            client = Beds24Client(http)
            await client.authenticate(refresh_token)
            cancelled = await client.get_bookings(status="cancelled")
    except Exception:
        logger.exception("archive.cancelled_check.beds24_error")
        return 0

    if not cancelled:
        return 0

    cancelled_contacts = [str(b["id"]) for b in cancelled]

    async with worker_session() as session:
        result = await session.execute(
            _SQL_ARCHIVE_CANCELLED, {"contacts": cancelled_contacts}
        )
        await session.commit()

    return result.rowcount


async def _run_archive_worker() -> None:
    while True:
        # Sleep until next midnight UTC
        now = datetime.now(UTC)
        tomorrow_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep((tomorrow_midnight - now).total_seconds())

        try:
            async with archive_lock:
                async with worker_session() as session:
                    r1 = await session.execute(_SQL_ARCHIVE_STALE_BEDS24)
                    r2 = await session.execute(_SQL_ARCHIVE_SILENT_BOOKINGS)
                    r3 = await session.execute(_SQL_ARCHIVE_NO_CHECKOUT)
                    r4 = await session.execute(_SQL_ARCHIVE_INACTIVE)
                    await session.commit()
                logger.info(
                    "archive.worker.ran beds24=%d silent=%d no_checkout=%d inactive=%d",
                    r1.rowcount,
                    r2.rowcount,
                    r3.rowcount,
                    r4.rowcount,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("archive.worker.error")

        try:
            cancelled = await _archive_cancelled_bookings()
            if cancelled:
                logger.info("archive.worker.cancelled archived=%d", cancelled)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("archive.worker.cancelled_check_error")


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
