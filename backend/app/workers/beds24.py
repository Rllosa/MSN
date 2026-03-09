"""Beds24 polling worker.

Polls the Beds24 inbox every `beds24_poll_interval_seconds` seconds, logs all
incoming messages, and rotates the refresh token on every auth call.

DB writes (conversation + message upsert) are implemented in SOLO-111.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import text

from app.clients.beds24 import Beds24AuthError, Beds24Client
from app.config import get_settings
from app.db.session import worker_session

logger = logging.getLogger(__name__)

# Module-level worker task — created on startup, cancelled on shutdown
_worker_task: asyncio.Task[None] | None = None

_CRED_KEY = "beds24_refresh_token"


async def _load_refresh_token() -> str:
    """Load refresh token from DB; fall back to env on first run."""
    try:
        async with worker_session() as session:
            result = await session.execute(
                text("SELECT value FROM api_credentials WHERE key = :key"),
                {"key": _CRED_KEY},
            )
            row = result.first()
            if row:
                return str(row[0])
    except Exception:
        logger.warning("beds24.token_load_failed falling_back_to_env=true")
    return get_settings().beds24_refresh_token


async def _persist_refresh_token(new_token: str) -> None:
    """Upsert new refresh token to DB immediately after auth."""
    async with worker_session() as session:
        await session.execute(
            text("""
                INSERT INTO api_credentials (key, value, updated_at)
                VALUES (:key, :value, NOW())
                ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value, updated_at = NOW()
            """),
            {"key": _CRED_KEY, "value": new_token},
        )
        await session.commit()


async def _poll_once(client: Beds24Client, refresh_token: str) -> str:
    """Authenticate, fetch inbox, log messages. Returns new refresh token.

    Token is persisted to DB before any subsequent API calls — if the process
    dies mid-poll the new token is safe.
    """
    new_token = await client.authenticate(refresh_token)
    await _persist_refresh_token(new_token)

    messages = await client.get_inbox()
    for msg in messages:
        logger.info(
            "beds24.message_received prop_id=%s booking_id=%s msg_id=%s",
            msg.get("propId"),
            msg.get("bookId"),
            msg.get("id"),
        )
        # TODO(SOLO-111): upsert conversation + message to DB

    if messages:
        logger.info("beds24.poll_complete count=%d", len(messages))
    else:
        logger.debug("beds24.poll_complete count=0")

    return new_token


async def _run_worker() -> None:
    """Main Beds24 polling loop — authenticates, polls, retries on error."""
    s = get_settings()
    refresh_token = await _load_refresh_token()
    backoff = 5  # seconds; doubled on consecutive failures, capped at 300

    async with httpx.AsyncClient(timeout=30) as http:
        client = Beds24Client(http)
        while True:
            try:
                refresh_token = await _poll_once(client, refresh_token)
                backoff = 5  # reset on success
                await asyncio.sleep(s.beds24_poll_interval_seconds)

            except asyncio.CancelledError:
                logger.info("beds24.worker_stopped")
                return

            except Beds24AuthError:
                logger.exception("beds24.auth_error backoff=%ds", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

            except Exception:
                logger.exception("beds24.error backoff=%ds", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)


def start_beds24_worker() -> None:
    """Create and schedule the Beds24 polling task. Called from FastAPI lifespan."""
    global _worker_task
    _worker_task = asyncio.create_task(_run_worker(), name="beds24_worker")
    logger.info("beds24.worker_started")


async def stop_beds24_worker() -> None:
    """Cancel the Beds24 polling task and wait for it to finish."""
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
