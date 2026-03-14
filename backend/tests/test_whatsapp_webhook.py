"""Integration tests for POST/GET /webhooks/whatsapp — SOLO-120.

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from alembic import command
from alembic.config import Config
from app.main import app

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

_WEBHOOK_URL = "/api/webhooks/whatsapp"


def _asyncpg_dsn() -> str:
    return _DB_URL.replace("postgresql+asyncpg://", "postgresql://")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sig(body: bytes, secret: str = "secret") -> str:
    """Compute X-Hub-Signature-256 header value for a payload."""
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _make_payload(
    wamid: str = "wamid.TEST001",
    phone: str = "15551234567",
    name: str = "Test Guest",
    body: str = "Hello!",
    timestamp: str = "1741234567",
    msg_type: str = "text",
) -> dict:
    msg: dict = {
        "id": wamid,
        "from": phone,
        "timestamp": timestamp,
        "type": msg_type,
    }
    if msg_type == "text":
        msg["text"] = {"body": body}
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "entry_id",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": "123"},
                            "contacts": [
                                {"profile": {"name": name}, "wa_id": phone}
                            ],
                            "messages": [msg],
                        }
                    }
                ],
            }
        ],
    }


def _post_headers(body: bytes) -> dict:
    return {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": _sig(body),
    }


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
async def client(migrated_db):
    from app.db.redis import dispose_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    init_engine()
    init_redis()
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    finally:
        await dispose_engine()
        await dispose_redis()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_valid_token(client: AsyncClient) -> None:
    """GET with correct verify token returns 200 and echoes the challenge."""
    r = await client.get(
        _WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify",
            "hub.challenge": "CHALLENGE_TOKEN_123",
        },
    )
    assert r.status_code == 200
    assert r.text == "CHALLENGE_TOKEN_123"


@pytest.mark.asyncio
async def test_verify_wrong_token(client: AsyncClient) -> None:
    """GET with wrong verify token returns 403."""
    r = await client.get(
        _WEBHOOK_URL,
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong-token",
            "hub.challenge": "xyz",
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_invalid_signature_returns_401(client: AsyncClient) -> None:
    """POST with invalid HMAC signature → 401, no DB writes."""
    payload_bytes = json.dumps(_make_payload()).encode()
    r = await client.post(
        _WEBHOOK_URL,
        content=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )
    assert r.status_code == 401

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM messages")
    finally:
        await conn.close()
    assert count == 0


@pytest.mark.asyncio
async def test_valid_inbound_text_stored(client: AsyncClient) -> None:
    """Valid signed payload → 200, conversation + message persisted, unread_count=1."""
    payload_dict = _make_payload(
        wamid="wamid.FULL001",
        phone="15559876543",
        name="Alice Guest",
        body="Is the pool heated?",
    )
    payload_bytes = json.dumps(payload_dict).encode()

    r = await client.post(
        _WEBHOOK_URL,
        content=payload_bytes,
        headers=_post_headers(payload_bytes),
    )
    assert r.status_code == 200

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        conv = await conn.fetchrow(
            "SELECT id::text, platform::text, guest_name, unread_count"
            " FROM conversations WHERE guest_contact = $1",
            "15559876543",
        )
        assert conv is not None
        assert conv["platform"] == "whatsapp"
        assert conv["guest_name"] == "Alice Guest"
        assert conv["unread_count"] == 1

        msg = await conn.fetchrow(
            "SELECT direction::text, body FROM messages"
            " WHERE conversation_id = $1",
            conv["id"],
        )
        assert msg is not None
        assert msg["direction"] == "inbound"
        assert msg["body"] == "Is the pool heated?"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_duplicate_wamid_dedup(client: AsyncClient) -> None:
    """Posting the same wamid twice results in exactly one message row."""
    payload_dict = _make_payload(
        wamid="wamid.DEDUP001",
        phone="15550001111",
        body="Hello twice",
    )
    payload_bytes = json.dumps(payload_dict).encode()
    headers = _post_headers(payload_bytes)

    r1 = await client.post(_WEBHOOK_URL, content=payload_bytes, headers=headers)
    r2 = await client.post(_WEBHOOK_URL, content=payload_bytes, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE raw_headers->>'wamid' = $1",
            "wamid.DEDUP001",
        )
    finally:
        await conn.close()
    assert count == 1


@pytest.mark.asyncio
async def test_status_update_ignored(client: AsyncClient) -> None:
    """Delivery receipt (no messages key) → 200, nothing written to DB."""
    status_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "eid",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "statuses": [
                                {"id": "wamid.OUTBOUND001", "status": "delivered"}
                            ],
                        }
                    }
                ],
            }
        ],
    }
    payload_bytes = json.dumps(status_payload).encode()

    r = await client.post(
        _WEBHOOK_URL,
        content=payload_bytes,
        headers=_post_headers(payload_bytes),
    )
    assert r.status_code == 200

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM messages")
    finally:
        await conn.close()
    assert count == 0
