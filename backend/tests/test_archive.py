"""Tests for SOLO-142 — Archive section.

Covers:
- checkout_date stored on Beds24 ingest
- auto-archive when checkout expired (> 7 days ago)
- auto-archive when booking is cancelled
- no auto-archive when unread messages exist
- manual archive via PATCH cascades to linked WhatsApp conv
- GET ?status=archived returns only archived conversations
- GET default (no status param) hides archived conversations
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
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

_ADMIN_EMAIL = "archive-test@example.com"
_ADMIN_PASSWORD = "archive-password-123"

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
async def db_engine(migrated_db):
    """Initialise the SQLAlchemy engine for tests that need worker_session."""
    from app.db.session import dispose_engine, init_engine

    init_engine()
    yield
    await dispose_engine()


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


async def _insert_conv(
    platform: str,
    guest_contact: str,
    guest_phone: str | None = None,
    status: str = "active",
    unread_count: int = 0,
) -> str:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "INSERT INTO conversations"
            " (platform, guest_name, guest_contact, guest_phone,"
            "  unread_count, status, last_message_at, created_at, updated_at)"
            " VALUES ($1, 'Test Guest', $2, $3, $4, $5, NOW(), NOW(), NOW())"
            " RETURNING id::text",
            platform,
            guest_contact,
            guest_phone,
            unread_count,
            status,
        )
        return row["id"]
    finally:
        await conn.close()


async def _get_conv_status(conv_id: str) -> str:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        return await conn.fetchval(
            "SELECT status FROM conversations WHERE id = $1::uuid", conv_id
        )
    finally:
        await conn.close()


async def _get_checkout_date(conv_id: str):
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        return await conn.fetchval(
            "SELECT checkout_date FROM conversations WHERE id = $1::uuid", conv_id
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_msg(booking_id: int, msg_id: int = 1) -> dict:
    return {
        "id": msg_id,
        "bookingId": booking_id,
        "propertyId": None,
        "time": "2026-01-01T10:00:00Z",
        "message": "Hello",
        "source": "guest",
    }


def _make_booking(
    booking_id: int, last_night: str | None, status: str = "confirmed"
) -> dict:
    return {
        "id": booking_id,
        "firstName": "John",
        "lastName": "Doe",
        "phone": None,
        "mobile": None,
        "departure": last_night,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkout_date_stored_on_ingest(db_engine):
    """checkout_date is populated from booking['lastNight'] on Beds24 ingest."""
    from app.db.ingest import ingest_beds24_message
    from app.db.session import worker_session

    last_night = "2026-03-10"
    msg = _make_msg(booking_id=99001)
    booking = _make_booking(99001, last_night=last_night)

    async with worker_session() as session:
        with patch("app.db.ingest._try_publish", new_callable=AsyncMock):
            await ingest_beds24_message(msg, "airbnb", booking, session)

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT checkout_date, status FROM conversations"
            " WHERE guest_contact = '99001'"
        )
    finally:
        await conn.close()

    assert row["checkout_date"] == date.fromisoformat(last_night)


@pytest.mark.asyncio
async def test_auto_archive_on_checkout_expired(db_engine):
    """Beds24 conv is auto-archived when checkout_date < today - 7 days."""
    from app.db.ingest import ingest_beds24_message
    from app.db.session import worker_session

    expired = (date.today() - timedelta(days=10)).isoformat()
    # Host (outbound) message → unread_count stays 0 → archive allowed
    msg = {**_make_msg(booking_id=99002), "source": "host"}
    booking = _make_booking(99002, last_night=expired)

    async with worker_session() as session:
        with patch("app.db.ingest._try_publish", new_callable=AsyncMock):
            await ingest_beds24_message(msg, "airbnb", booking, session)

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        status = await conn.fetchval(
            "SELECT status FROM conversations WHERE guest_contact = '99002'"
        )
    finally:
        await conn.close()

    assert status == "archived"


@pytest.mark.asyncio
async def test_no_auto_archive_when_unread(db_engine):
    """Beds24 conv is NOT auto-archived when there are unread messages."""
    from app.db.ingest import ingest_beds24_message
    from app.db.session import worker_session

    expired = (date.today() - timedelta(days=10)).isoformat()
    # Inbound message → unread_count will be 1 after ingest
    msg = _make_msg(booking_id=99003)
    booking = _make_booking(99003, last_night=expired)

    async with worker_session() as session:
        with patch("app.db.ingest._try_publish", new_callable=AsyncMock):
            await ingest_beds24_message(msg, "airbnb", booking, session)

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT status, unread_count FROM conversations"
            " WHERE guest_contact = '99003'"
        )
    finally:
        await conn.close()

    assert row["unread_count"] == 1
    assert row["status"] == "active"  # NOT archived because unread > 0


@pytest.mark.asyncio
async def test_cancelled_booking_archived(db_engine):
    """Beds24 conv is auto-archived immediately when booking status is cancelled."""
    from app.db.ingest import ingest_beds24_message
    from app.db.session import worker_session

    # Host (outbound) message → unread_count stays 0 → archive allowed
    msg = {**_make_msg(booking_id=99004), "source": "host"}
    booking = _make_booking(99004, last_night="2026-03-15", status="cancelled")

    async with worker_session() as session:
        with patch("app.db.ingest._try_publish", new_callable=AsyncMock):
            await ingest_beds24_message(msg, "airbnb", booking, session)

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        status = await conn.fetchval(
            "SELECT status FROM conversations WHERE guest_contact = '99004'"
        )
    finally:
        await conn.close()

    assert status == "archived"


@pytest.mark.asyncio
async def test_patch_archive_cascades_to_linked_wa(ac: AsyncClient, token: str):
    """Archiving a booking conv also archives its linked WhatsApp conv."""
    phone = "33612345678"
    booking_id = await _insert_conv("airbnb", "99005", guest_phone=phone)
    wa_id = await _insert_conv("whatsapp", phone, guest_phone=phone)

    resp = await ac.patch(
        f"/api/conversations/{booking_id}",
        json={"status": "archived"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

    assert await _get_conv_status(wa_id) == "archived"


@pytest.mark.asyncio
async def test_patch_unarchive_cascades_to_linked_wa(ac: AsyncClient, token: str):
    """Unarchiving a booking conv also unarchives its linked WhatsApp conv."""
    phone = "33698765432"
    booking_id = await _insert_conv(
        "airbnb", "99006", guest_phone=phone, status="archived"
    )
    wa_id = await _insert_conv("whatsapp", phone, guest_phone=phone, status="archived")

    resp = await ac.patch(
        f"/api/conversations/{booking_id}",
        json={"status": "active"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"

    assert await _get_conv_status(wa_id) == "active"


@pytest.mark.asyncio
async def test_list_archived_conversations(ac: AsyncClient, token: str):
    """GET ?status=archived returns only archived conversations."""
    await _insert_conv("airbnb", "99007@reply.airbnb.com", status="active")
    await _insert_conv("booking", "99008", status="archived")

    resp = await ac.get(
        "/api/conversations/?status=archived",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    contacts = {c["guest_contact"] for c in data["items"]}
    assert "99008" in contacts
    assert "99007@reply.airbnb.com" not in contacts


@pytest.mark.asyncio
async def test_list_default_hides_archived(ac: AsyncClient, token: str):
    """Default GET (no status param) returns only active conversations."""
    await _insert_conv("airbnb", "99009@reply.airbnb.com", status="active")
    await _insert_conv("booking", "99010", status="archived")

    resp = await ac.get(
        "/api/conversations/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    contacts = {c["guest_contact"] for c in data["items"]}
    assert "99009@reply.airbnb.com" in contacts
    assert "99010" not in contacts
