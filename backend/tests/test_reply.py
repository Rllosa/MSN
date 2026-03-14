"""Tests for POST /conversations/{id}/reply — SOLO-118.

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from alembic import command
from alembic.config import Config
from app.auth.hashing import hash_password
from app.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ADMIN_EMAIL = "reply-test@example.com"
_ADMIN_PASSWORD = "reply-password-123"

_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://msn:msn@localhost:5433/msn_test",
)
_REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6380/0")

_ENV_OVERRIDES = {
    "DATABASE_URL": _DB_URL,
    "REDIS_URL": _REDIS_URL,
    "JWT_SECRET_KEY": "test-secret-key-for-tests-only",
    "IMAP_HOST": "imap.example.com",
    "IMAP_USER": "user",
    "IMAP_PASSWORD": "pass",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USER": "user",
    "SMTP_PASSWORD": "pass",
    "SMTP_FROM": "noreply@example.com",
    "WHATSAPP_PHONE_NUMBER_ID": "123",
    "WHATSAPP_ACCESS_TOKEN": "tok",
    "WHATSAPP_VERIFY_TOKEN": "verify",
    "WHATSAPP_APP_SECRET": "secret",
    "BEDS24_REFRESH_TOKEN": "test-refresh-token",
}

_REPLY_BODY = {"content": "Hello, thank you for your inquiry!"}


def _asyncpg_dsn() -> str:
    return _DB_URL.replace("postgresql+asyncpg://", "postgresql://")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def migrated_db(monkeypatch):
    for k, v in _ENV_OVERRIDES.items():
        monkeypatch.setenv(k, v)

    from app.config import get_settings

    get_settings.cache_clear()

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.execute("CREATE SCHEMA public")
        await conn.execute("DROP TYPE IF EXISTS platform_enum CASCADE")
        await conn.execute("DROP TYPE IF EXISTS direction_enum CASCADE")
    finally:
        await conn.close()

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", _DB_URL)
    await asyncio.to_thread(command.upgrade, cfg, "head")

    yield

    get_settings.cache_clear()


@pytest_asyncio.fixture()
async def ac(migrated_db):
    from app.db.redis import dispose_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    init_engine()
    init_redis()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        await dispose_engine()
        await dispose_redis()


@pytest_asyncio.fixture()
async def token(migrated_db, ac: AsyncClient) -> str:
    pw_hash = hash_password(_ADMIN_PASSWORD)
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await conn.execute(
            "INSERT INTO users (email, password_hash, is_active, is_admin)"
            " VALUES ($1, $2, TRUE, TRUE)",
            _ADMIN_EMAIL,
            pw_hash,
        )
    finally:
        await conn.close()

    r = await ac.post(
        "/api/auth/login",
        json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


async def _insert_conv(platform: str, guest_contact: str) -> str:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "INSERT INTO conversations"
            " (platform, guest_name, guest_contact,"
            "  last_message_at, created_at, updated_at)"
            " VALUES ($1::platform_enum, 'Test Guest', $2, NOW(), NOW(), NOW())"
            " RETURNING id::text",
            platform,
            guest_contact,
        )
    finally:
        await conn.close()
    return row["id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_smtp_path(ac: AsyncClient, token: str) -> None:
    """SMTP path: aiosmtplib.send called with correct recipient, message stored."""
    conv_id = await _insert_conv("airbnb", "TOKEN123abc@reply.airbnb.com")
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.clients.smtp.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            json=_REPLY_BODY,
            headers=headers,
        )

    assert resp.status_code == 201
    mock_send.assert_awaited_once()
    sent_msg = mock_send.call_args.args[0]
    assert sent_msg["To"] == "TOKEN123abc@reply.airbnb.com"

    data = resp.json()
    assert data["direction"] == "outbound"
    assert data["body"] == _REPLY_BODY["content"]


@pytest.mark.asyncio
async def test_reply_beds24_path(ac: AsyncClient, token: str) -> None:
    """Beds24 path: Beds24Client.post_message called with correct booking ID."""
    conv_id = await _insert_conv("airbnb", "82940750")
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch(
            "app.api.conversations.Beds24Client.authenticate",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.conversations.Beds24Client.post_message",
            new_callable=AsyncMock,
        ) as mock_post,
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            json=_REPLY_BODY,
            headers=headers,
        )

    assert resp.status_code == 201
    mock_post.assert_awaited_once_with(82940750, _REPLY_BODY["content"])
    assert resp.json()["direction"] == "outbound"


@pytest.mark.asyncio
async def test_reply_smtp_failure_returns_502(ac: AsyncClient, token: str) -> None:
    """SMTP failure → 502, no message row inserted."""
    conv_id = await _insert_conv("airbnb", "TOKENFAIL@reply.airbnb.com")
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "app.clients.smtp.aiosmtplib.send",
        new_callable=AsyncMock,
        side_effect=Exception("SMTP connection refused"),
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            json=_REPLY_BODY,
            headers=headers,
        )

    assert resp.status_code == 502

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = $1", conv_id
        )
    finally:
        await conn.close()
    assert count == 0


@pytest.mark.asyncio
async def test_reply_beds24_failure_returns_502(ac: AsyncClient, token: str) -> None:
    """Beds24 failure → 502, no message row inserted."""
    conv_id = await _insert_conv("airbnb", "99999999")
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch(
            "app.api.conversations.Beds24Client.authenticate",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.conversations.Beds24Client.post_message",
            new_callable=AsyncMock,
            side_effect=Exception("Beds24 API error"),
        ),
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            json=_REPLY_BODY,
            headers=headers,
        )

    assert resp.status_code == 502

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = $1", conv_id
        )
    finally:
        await conn.close()
    assert count == 0


@pytest.mark.asyncio
async def test_reply_booking_beds24_path(ac: AsyncClient, token: str) -> None:
    """Booking.com conversation uses Beds24 path (same as Airbnb booking)."""
    conv_id = await _insert_conv("booking", "82940752")
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch(
            "app.api.conversations.Beds24Client.authenticate",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.conversations.Beds24Client.post_message",
            new_callable=AsyncMock,
        ) as mock_post,
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            json=_REPLY_BODY,
            headers=headers,
        )

    assert resp.status_code == 201
    mock_post.assert_awaited_once_with(82940752, _REPLY_BODY["content"])
