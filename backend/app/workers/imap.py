from __future__ import annotations

import asyncio
import email
import logging
from collections.abc import Awaitable, Callable

import aioimaplib

from app.config import get_settings

logger = logging.getLogger(__name__)

# Module-level worker task handle — created on startup, cancelled on shutdown
_worker_task: asyncio.Task[None] | None = None


async def process_email(raw_bytes: bytes) -> None:
    """No-op stub — replaced by SOLO-109/110 parsers."""
    msg = email.message_from_bytes(raw_bytes)
    logger.debug(
        "imap.email_received message_id=%s",
        msg.get("Message-ID", "<unknown>"),
    )


async def _poll_once(
    client: aioimaplib.IMAP4_SSL,
    on_email: Callable[[bytes], Awaitable[None]],
) -> None:
    """Fetch all UNSEEN messages, call on_email for each, mark SEEN."""
    await client.select("INBOX")
    _, data = await client.search("UNSEEN")
    # data[0] is b"" when there are no results, or b"1 2 3" space-separated UIDs
    uids = data[0].split() if data[0] else []
    for uid in uids:
        _, msg_data = await client.fetch(uid, "(RFC822)")
        raw = msg_data[1]  # bytes — the full RFC 5322 message
        await on_email(raw)
        await client.store(uid, "+FLAGS", "\\Seen")
    if uids:
        logger.info("imap.poll_complete fetched=%d", len(uids))


async def _run_worker(on_email: Callable[[bytes], Awaitable[None]]) -> None:
    """Main polling loop — connects, polls every interval, retries on error."""
    s = get_settings()
    backoff = 5  # seconds; doubled on each consecutive failure, capped at 300

    while True:
        try:
            client = aioimaplib.IMAP4_SSL(host=s.imap_host, port=s.imap_port)
            await client.wait_hello_from_server()
            await client.login(s.imap_user, s.imap_password)
            logger.info("imap.connected host=%s user=%s", s.imap_host, s.imap_user)
            backoff = 5  # reset on successful connect

            while True:
                await _poll_once(client, on_email)
                await asyncio.sleep(s.imap_poll_interval_seconds)

        except asyncio.CancelledError:
            # Clean shutdown — do not retry
            logger.info("imap.worker_stopped")
            return

        except Exception:
            # Log + backoff + retry; never crash the app (Rule 1.3)
            logger.exception("imap.error backoff=%ds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)


def start_imap_worker(
    on_email: Callable[[bytes], Awaitable[None]] = process_email,
) -> None:
    """Create and schedule the IMAP polling task. Called from FastAPI lifespan."""
    global _worker_task
    _worker_task = asyncio.create_task(_run_worker(on_email), name="imap_worker")
    logger.info("imap.worker_started")


async def stop_imap_worker() -> None:
    """Cancel the IMAP polling task and wait for it to finish."""
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
