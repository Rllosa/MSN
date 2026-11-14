from __future__ import annotations

import asyncio
import email
import logging
from collections.abc import Awaitable, Callable

import aioimaplib

from app.config import get_settings
from app.db.ingest import ingest_airbnb_email
from app.db.session import worker_session
from app.parsers.airbnb import is_airbnb_email, parse_airbnb_email

logger = logging.getLogger(__name__)

# Module-level worker task handle — created on startup, cancelled on shutdown
_worker_task: asyncio.Task[None] | None = None


async def process_email(raw_bytes: bytes) -> None:
    """Route raw email to the appropriate platform parser."""
    msg = email.message_from_bytes(raw_bytes)

    if is_airbnb_email(msg):
        parsed = parse_airbnb_email(raw_bytes)
        if parsed:
            async with worker_session() as session:
                await ingest_airbnb_email(parsed, session)
    else:
        logger.debug(
            "imap.email_skipped message_id=%s from=%s",
            msg.get("Message-ID", "<unknown>"),
            msg.get("From", "<unknown>"),
        )


class ImapCommandError(RuntimeError):
    """An IMAP command answered something other than OK (NO / BAD)."""


def _describe(lines: object) -> str:
    """Human-readable server answer for logs (lines are bytes in aioimaplib)."""
    if not isinstance(lines, list):
        return str(lines)
    return " ".join(
        x.decode(errors="replace") if isinstance(x, bytes | bytearray) else str(x)
        for x in lines
    )[:300]


def _extract_message(lines: list[object]) -> bytes | None:
    """Return the raw RFC 5322 message from a FETCH response.

    aioimaplib returns the message literal as a ``bytearray`` line, e.g.
    [b'1 FETCH (RFC822 {1234}', bytearray(b'...'), b')', b'Fetch completed'].
    """
    for line in lines:
        if isinstance(line, bytearray):
            return bytes(line)
    return None


async def _close(client: aioimaplib.IMAP4_SSL | None) -> None:
    """Log out and drop the connection. Never raises.

    Previously failed connections were never closed: each retry opened a new one,
    until the mail server refused logins (mail_max_userip_connections exceeded).
    """
    if client is None:
        return
    try:
        await asyncio.wait_for(client.logout(), timeout=10)
    except Exception:  # noqa: BLE001 — best effort, connection may already be dead
        logger.debug("imap.logout_failed", exc_info=True)


async def _poll_once(
    client: aioimaplib.IMAP4_SSL,
    on_email: Callable[[bytes], Awaitable[None]],
) -> None:
    """Fetch all UNSEEN messages, call on_email for each, mark SEEN."""
    result, data = await client.select("INBOX")
    if result != "OK":
        raise ImapCommandError(f"SELECT INBOX failed: {result} {_describe(data)}")

    result, data = await client.search("UNSEEN")
    if result != "OK":
        raise ImapCommandError(f"SEARCH UNSEEN failed: {result} {_describe(data)}")

    # data[0] is b"" when there are no results, or b"1 2 3" space-separated ids.
    # aioimaplib expects str message sets: passing bytes sends "b'1'" to the server.
    ids = [
        raw_id.decode() if isinstance(raw_id, bytes | bytearray) else str(raw_id)
        for raw_id in (data[0].split() if data and data[0] else [])
    ]

    processed = 0
    for msg_id in ids:
        result, msg_data = await client.fetch(msg_id, "(RFC822)")
        raw = _extract_message(msg_data) if result == "OK" else None
        if raw is None:
            logger.warning(
                "imap.fetch_failed id=%s result=%s answer=%s",
                msg_id,
                result,
                _describe(msg_data),
            )
            continue

        try:
            await on_email(raw)
            processed += 1
        except Exception:
            # Do not let one bad email block the inbox forever: log it (with its id
            # for manual re-processing) and still mark it as seen below.
            logger.exception("imap.process_failed id=%s", msg_id)

        await client.store(msg_id, "+FLAGS", "\\Seen")

    if ids:
        logger.info("imap.poll_complete unseen=%d processed=%d", len(ids), processed)


async def _run_worker(on_email: Callable[[bytes], Awaitable[None]]) -> None:
    """Main polling loop — connects, polls every interval, retries on error."""
    s = get_settings()
    backoff = 5  # seconds; doubled on each consecutive failure, capped at 300

    while True:
        client: aioimaplib.IMAP4_SSL | None = None
        try:
            client = aioimaplib.IMAP4_SSL(host=s.imap_host, port=s.imap_port)
            await client.wait_hello_from_server()
            result, data = await client.login(s.imap_user, s.imap_password)
            if result != "OK":
                raise ImapCommandError(f"LOGIN failed: {result} {_describe(data)}")
            logger.info("imap.connected host=%s user=%s", s.imap_host, s.imap_user)

            while True:
                await _poll_once(client, on_email)
                backoff = 5  # reset only after a successful poll, not just a connect
                await asyncio.sleep(s.imap_poll_interval_seconds)

        except asyncio.CancelledError:
            # Clean shutdown — do not retry
            await _close(client)
            logger.info("imap.worker_stopped")
            return

        except Exception:
            # Log + close + backoff + retry; never crash the app (Rule 1.3)
            logger.exception("imap.error backoff=%ds", backoff)
            await _close(client)
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
