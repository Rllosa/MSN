"""Integration tests for app/db/ingest.py — idempotent message upsert pipeline.

Requires live PostgreSQL (port 5433) from:
    docker compose up -d postgres redis
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import asyncpg
import pytest
import pytest_asyncio

from alembic import command
from alembic.config import Config

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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
    """Reset DB schema, run all migrations, yield."""
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
async def db_session(migrated_db):
    """Yield an AsyncSession backed by the test DB."""
    from app.db.session import dispose_engine, init_engine, worker_session

    init_engine()
    try:
        async with worker_session() as session:
            yield session
    finally:
        await dispose_engine()


@pytest_asyncio.fixture()
async def property_in_db(migrated_db):
    """Insert a test property and return its UUID."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO properties (name, slug, beds24_property_id)
            VALUES ('Lagoon', 'lagoon', 314537)
            RETURNING id::text
            """
        )
        return row["id"]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parsed(
    msg_id: str = "<test@airbnb.com>",
    reply_to: str = "TOKEN123@reply.airbnb.com",
    body: str = "Hello, is the pool available?",
    property_name: str = "Lagoon",
    sent_at: datetime | None = None,
):
    from app.parsers.airbnb import AirbnbParsedEmail

    return AirbnbParsedEmail(
        guest_name="Alice Guest",
        message_body=body,
        reply_to=reply_to,
        platform_conversation_id="TOKEN123",
        property_name=property_name,
        message_id_header=msg_id,
        sent_at=sent_at or datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC),
    )


def _make_beds24_msg(
    msg_id: int = 999001,
    booking_id: int = 82940750,
    property_id: int = 314537,
    body: str = "What time is check-in?",
    time: str = "2026-03-10T14:00:00Z",
):
    return {
        "id": msg_id,
        "bookingId": booking_id,
        "propertyId": property_id,
        "source": "guest",
        "message": body,
        "time": time,
    }


def _make_booking(
    booking_id: int = 82940750,
    channel: str = "airbnb",
    first: str = "Bob",
    last: str = "Guest",
):
    return {
        "id": booking_id,
        "channel": channel,
        "firstName": first,
        "lastName": last,
    }


# ---------------------------------------------------------------------------
# compute_hash — pure unit test, no DB
# ---------------------------------------------------------------------------


def test_compute_hash_deterministic() -> None:
    """Same input always produces the same 64-char hex SHA-256."""
    from app.db.ingest import compute_hash

    h1 = compute_hash("some-message-id")
    h2 = compute_hash("some-message-id")
    assert h1 == h2
    assert len(h1) == 64
    assert h1 != compute_hash("different-message-id")


# ---------------------------------------------------------------------------
# ingest_airbnb_email — replay test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_airbnb_replay_inserts_once(db_session, property_in_db) -> None:
    """Processing the same parsed email 3 times → exactly 1 message row."""
    from app.db.ingest import ingest_airbnb_email

    parsed = _make_parsed()

    r1 = await ingest_airbnb_email(parsed, db_session)
    r2 = await ingest_airbnb_email(parsed, db_session)
    r3 = await ingest_airbnb_email(parsed, db_session)

    assert r1 is True  # first insert
    assert r2 is False  # duplicate
    assert r3 is False  # duplicate

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM messages")
        assert count == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_airbnb_two_emails_same_conversation(db_session, property_in_db) -> None:
    """Two distinct emails from the same reply-to → 1 conversation, 2 messages."""
    from app.db.ingest import ingest_airbnb_email

    p1 = _make_parsed(msg_id="<msg1@airbnb.com>", body="First message")
    p2 = _make_parsed(msg_id="<msg2@airbnb.com>", body="Follow-up question")

    await ingest_airbnb_email(p1, db_session)
    await ingest_airbnb_email(p2, db_session)

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        conv_count = await conn.fetchval("SELECT COUNT(*) FROM conversations")
        msg_count = await conn.fetchval("SELECT COUNT(*) FROM messages")
        assert conv_count == 1
        assert msg_count == 2
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_airbnb_unknown_property_sets_null(db_session, migrated_db) -> None:
    """When property name has no DB match, property_id is NULL — message still saved."""
    from app.db.ingest import ingest_airbnb_email

    parsed = _make_parsed(property_name="NonExistentVilla")
    inserted = await ingest_airbnb_email(parsed, db_session)

    assert inserted is True
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT property_id FROM conversations WHERE guest_contact = $1",
            parsed.reply_to,
        )
        assert row is not None
        assert row["property_id"] is None
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# ingest_beds24_message — dedup test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_beds24_dedup(db_session, property_in_db) -> None:
    """Same Beds24 message ID inserted twice → exactly 1 message row."""
    from app.db.ingest import ingest_beds24_message

    msg = _make_beds24_msg()
    booking = _make_booking()

    r1 = await ingest_beds24_message(msg, "airbnb", booking, db_session)
    r2 = await ingest_beds24_message(msg, "airbnb", booking, db_session)

    assert r1 is True
    assert r2 is False

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM messages")
        assert count == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_beds24_platform_routing(db_session, property_in_db) -> None:
    """Airbnb and Booking.com messages land in separate conversations."""
    from app.db.ingest import ingest_beds24_message

    airbnb_msg = _make_beds24_msg(msg_id=1001, booking_id=100)
    booking_msg = _make_beds24_msg(msg_id=1002, booking_id=200)
    airbnb_booking = _make_booking(booking_id=100, channel="airbnb")
    booking_booking = _make_booking(booking_id=200, channel="booking")

    await ingest_beds24_message(airbnb_msg, "airbnb", airbnb_booking, db_session)
    await ingest_beds24_message(booking_msg, "booking", booking_booking, db_session)

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            "SELECT platform, guest_contact FROM conversations ORDER BY platform"
        )
        assert len(rows) == 2
        platforms = {r["platform"] for r in rows}
        assert platforms == {"airbnb", "booking"}
    finally:
        await conn.close()
