"""Conversations + messages API tests.

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis
"""

from __future__ import annotations

import asyncio
import os
import uuid

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

_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASSWORD = "admin-password-123"

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
    """Reset DB schema and run all migrations."""
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
async def client(migrated_db):
    """AsyncClient backed by the FastAPI ASGI app."""
    from app.db.redis import dispose_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    init_engine()
    init_redis()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        await dispose_engine()
        await dispose_redis()


@pytest_asyncio.fixture()
async def admin_in_db(migrated_db):
    """Insert an admin user via asyncpg."""
    pw_hash = hash_password(_ADMIN_PASSWORD)
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "INSERT INTO users (email, password_hash, is_active, is_admin)"
            " VALUES ($1, $2, TRUE, TRUE) RETURNING id::text",
            _ADMIN_EMAIL,
            pw_hash,
        )
    finally:
        await conn.close()
    return {"id": row["id"], "email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD}


async def _token(client: AsyncClient) -> str:
    r = await client.post(
        "/api/auth/login",
        json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


async def _insert_conversation(
    conn: asyncpg.Connection,
    *,
    platform: str = "airbnb",
    guest_name: str = "Test Guest",
    guest_contact: str | None = None,
    status: str = "active",
    unread_count: int = 0,
) -> str:
    """Insert a conversation and return its UUID string."""
    contact = guest_contact or f"contact-{uuid.uuid4()}@example.com"
    row = await conn.fetchrow(
        "INSERT INTO conversations"
        " (platform, guest_name, guest_contact, status, unread_count,"
        "  last_message_at, created_at, updated_at)"
        " VALUES ($1::platform_enum, $2, $3, $4, $5, NOW(), NOW(), NOW())"
        " RETURNING id::text",
        platform,
        guest_name,
        contact,
        status,
        unread_count,
    )
    return row["id"]


async def _insert_message(
    conn: asyncpg.Connection,
    conv_id: str,
    *,
    body: str = "Hello",
    direction: str = "inbound",
) -> str:
    """Insert a message and return its UUID string."""
    row = await conn.fetchrow(
        "INSERT INTO messages"
        " (conversation_id, message_id_hash, direction, body, sent_at, created_at)"
        " VALUES ($1, $2, $3::direction_enum, $4, NOW(), NOW())"
        " RETURNING id::text",
        conv_id,
        str(uuid.uuid4()),
        direction,
        body,
    )
    return row["id"]


# ---------------------------------------------------------------------------
# Tests — auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_conversations_unauthenticated(client):
    r = await client.get("/api/conversations/")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Tests — list endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_conversations_empty(admin_in_db, client):
    token = await _token(client)
    r = await client.get(
        "/api/conversations/", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_list_conversations_default_active_only(admin_in_db, client):
    """Default list returns only active conversations."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await _insert_conversation(conn, platform="airbnb", status="active")
        await _insert_conversation(conn, platform="booking", status="archived")
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        "/api/conversations/", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["platform"] == "airbnb"


@pytest.mark.asyncio
async def test_filter_by_platform(admin_in_db, client):
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await _insert_conversation(conn, platform="airbnb")
        await _insert_conversation(conn, platform="booking")
        await _insert_conversation(conn, platform="airbnb")
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        "/api/conversations/?platform=airbnb",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert all(item["platform"] == "airbnb" for item in body["items"])


@pytest.mark.asyncio
async def test_filter_by_multiple_properties(admin_in_db, client):
    """property_id=id1,id2 returns conversations for both properties."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        # Create 3 properties
        _prop_sql = (
            "INSERT INTO properties (name, slug)" " VALUES ($1, $2) RETURNING id::text"
        )
        p1 = await conn.fetchval(_prop_sql, "Apt1", "apt1")
        p2 = await conn.fetchval(_prop_sql, "Apt2", "apt2")
        p3 = await conn.fetchval(_prop_sql, "Apt3", "apt3")

        # Conversations for p1, p2, p3
        _conv_sql = (
            "INSERT INTO conversations"
            " (platform, guest_name, guest_contact,"
            "  property_id, status, created_at, updated_at)"
            " VALUES ($1::platform_enum, $2, $3, $4, 'active', NOW(), NOW())"
        )
        await conn.execute(_conv_sql, "airbnb", "G1", "c1@x.com", p1)
        await conn.execute(_conv_sql, "booking", "G2", "c2@x.com", p2)
        await conn.execute(_conv_sql, "airbnb", "G3", "c3@x.com", p3)
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        f"/api/conversations/?property_id={p1},{p2}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    names = {item["guest_name"] for item in body["items"]}
    assert names == {"G1", "G2"}


@pytest.mark.asyncio
async def test_search_by_guest_name(admin_in_db, client):
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await _insert_conversation(conn, guest_name="Bojana Marsala")
        await _insert_conversation(conn, guest_name="John Smith")
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        "/api/conversations/?search=Bojana",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["guest_name"] == "Bojana Marsala"


@pytest.mark.asyncio
async def test_search_by_booking_id(admin_in_db, client):
    """guest_contact (booking ID) is also searched."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await _insert_conversation(conn, guest_name="Guest A", guest_contact="83068787")
        await _insert_conversation(conn, guest_name="Guest B", guest_contact="99999999")
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        "/api/conversations/?search=83068787",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["guest_name"] == "Guest A"


@pytest.mark.asyncio
async def test_unread_sorted_first(admin_in_db, client):
    """Conversations with unread_count > 0 appear before read ones."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await _insert_conversation(conn, guest_name="Read Guest", unread_count=0)
        await _insert_conversation(conn, guest_name="Unread Guest", unread_count=3)
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        "/api/conversations/", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["guest_name"] == "Unread Guest"
    assert items[1]["guest_name"] == "Read Guest"


@pytest.mark.asyncio
async def test_pagination_no_overlap(admin_in_db, client):
    """Page 2 returns different items than page 1 with no overlap."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        for i in range(5):
            await _insert_conversation(conn, guest_name=f"Guest {i}")
    finally:
        await conn.close()

    token = await _token(client)
    r1 = await client.get(
        "/api/conversations/?limit=3&offset=0",
        headers={"Authorization": f"Bearer {token}"},
    )
    r2 = await client.get(
        "/api/conversations/?limit=3&offset=3",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200

    ids1 = {item["id"] for item in r1.json()["items"]}
    ids2 = {item["id"] for item in r2.json()["items"]}
    assert ids1.isdisjoint(ids2)
    assert r1.json()["total"] == 5
    assert len(r2.json()["items"]) == 2  # 5 total, 3 on page 1


# ---------------------------------------------------------------------------
# Tests — detail endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_conversation_detail(admin_in_db, client):
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        conv_id = await _insert_conversation(conn, guest_name="Detail Guest")
        await _insert_message(conn, conv_id, body="Hi there")
        await _insert_message(conn, conv_id, body="How are you?")
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        f"/api/conversations/{conv_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["guest_name"] == "Detail Guest"
    assert len(body["messages"]) == 2
    # Messages should be in chronological order
    assert body["messages"][0]["body"] == "Hi there"
    assert body["messages"][1]["body"] == "How are you?"


@pytest.mark.asyncio
async def test_get_conversation_not_found(admin_in_db, client):
    token = await _token(client)
    r = await client.get(
        f"/api/conversations/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests — PATCH endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_archive_conversation(admin_in_db, client):
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        conv_id = await _insert_conversation(conn, status="active")
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.patch(
        f"/api/conversations/{conv_id}",
        json={"status": "archived"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"

    # Should no longer appear in default (active) list
    list_r = await client.get(
        "/api/conversations/", headers={"Authorization": f"Bearer {token}"}
    )
    ids = [item["id"] for item in list_r.json()["items"]]
    assert conv_id not in ids


@pytest.mark.asyncio
async def test_patch_mark_read_resets_unread_count(admin_in_db, client):
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        conv_id = await _insert_conversation(conn, unread_count=5)
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.patch(
        f"/api/conversations/{conv_id}",
        json={"mark_read": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["unread_count"] == 0


# ---------------------------------------------------------------------------
# Tests — messages endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_messages_no_cursor(admin_in_db, client):
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        conv_id = await _insert_conversation(conn)
        for i in range(3):
            await _insert_message(conn, conv_id, body=f"Message {i}")
    finally:
        await conn.close()

    token = await _token(client)
    r = await client.get(
        f"/api/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 3
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_messages_conv_not_found(admin_in_db, client):
    token = await _token(client)
    r = await client.get(
        f"/api/conversations/{uuid.uuid4()}/messages",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tests — unread_count via ingest
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unread_count_increments_on_ingest(migrated_db):
    """ingest_airbnb_email increments unread_count on each new message."""
    from datetime import UTC, datetime

    from app.db.ingest import ingest_airbnb_email
    from app.db.redis import dispose_redis, init_redis
    from app.db.session import dispose_engine, init_engine, worker_session
    from app.parsers.airbnb import AirbnbParsedEmail

    init_engine()
    init_redis()
    try:
        base = AirbnbParsedEmail(
            guest_name="Ingest Guest",
            property_name="Nonexistent Property",
            message_body="Hello",
            reply_to="guest@airbnb.com",
            platform_conversation_id="conv-unread-test",
            message_id_header="<msg1@airbnb.com>",
            sent_at=datetime.now(UTC),
        )

        async with worker_session() as session:
            await ingest_airbnb_email(base, session)

        # Second unique message — different Message-ID
        msg2 = AirbnbParsedEmail(
            guest_name="Ingest Guest",
            property_name="Nonexistent Property",
            message_body="World",
            reply_to="guest@airbnb.com",
            platform_conversation_id="conv-unread-test",
            message_id_header="<msg2@airbnb.com>",
            sent_at=datetime.now(UTC),
        )
        async with worker_session() as session:
            await ingest_airbnb_email(msg2, session)

        conn = await asyncpg.connect(_asyncpg_dsn())
        try:
            count = await conn.fetchval(
                "SELECT unread_count FROM conversations"
                " WHERE guest_contact = 'guest@airbnb.com'"
            )
        finally:
            await conn.close()

        assert count == 2
    finally:
        await dispose_engine()
        await dispose_redis()
