"""Tests for POST /conversations/{id}/reply — WhatsApp path (SOLO-121).

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis
"""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

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

_ADMIN_EMAIL = "wa-reply-test@example.com"
_ADMIN_PASSWORD = "wa-reply-password-123"

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
    "WHATSAPP_PHONE_NUMBER_ID": "123456789",
    "WHATSAPP_ACCESS_TOKEN": "test-wa-token",
    "WHATSAPP_VERIFY_TOKEN": "verify",
    "WHATSAPP_APP_SECRET": "secret",
    "BEDS24_REFRESH_TOKEN": "test-refresh-token",
}

_REPLY_BODY = {"content": "Bonjour, votre réservation est confirmée !"}
_FAKE_WAMID = "wamid.test_reply_001"
_GUEST_PHONE = "33612345678"

_META_SUCCESS_RESPONSE = {
    "messaging_product": "whatsapp",
    "contacts": [{"input": _GUEST_PHONE, "wa_id": _GUEST_PHONE}],
    "messages": [{"id": _FAKE_WAMID}],
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


async def _insert_whatsapp_conv(phone: str = _GUEST_PHONE) -> str:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "INSERT INTO conversations"
            " (platform, guest_name, guest_contact,"
            "  last_message_at, created_at, updated_at)"
            " VALUES ('whatsapp'::platform_enum, 'Test Guest', $1, NOW(), NOW(), NOW())"
            " RETURNING id::text",
            phone,
        )
    finally:
        await conn.close()
    return row["id"]


def _mock_meta_success():
    """Return a mock httpx.Response for a successful Meta API call."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _META_SUCCESS_RESPONSE
    mock_resp.text = json.dumps(_META_SUCCESS_RESPONSE)
    return mock_resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_whatsapp_reply_success(ac: AsyncClient, token: str) -> None:
    """Meta API success → 201, outbound message stored with wamid in raw_headers."""
    conv_id = await _insert_whatsapp_conv()
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "app.clients.whatsapp.WhatsAppClient.send_text",
        new_callable=AsyncMock,
        return_value=_FAKE_WAMID,
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            json=_REPLY_BODY,
            headers=headers,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["direction"] == "outbound"
    assert data["body"] == _REPLY_BODY["content"]

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT raw_headers FROM messages WHERE conversation_id = $1", conv_id
        )
    finally:
        await conn.close()

    assert row is not None
    raw = json.loads(row["raw_headers"])
    assert raw["reply_path"] == "whatsapp"
    assert raw["wamid"] == _FAKE_WAMID


@pytest.mark.asyncio
async def test_whatsapp_reply_api_failure_returns_502(
    ac: AsyncClient, token: str
) -> None:
    """Meta API 400 → 502, no message row inserted."""
    from app.clients.whatsapp import WhatsAppAPIError

    conv_id = await _insert_whatsapp_conv()
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "app.clients.whatsapp.WhatsAppClient.send_text",
        new_callable=AsyncMock,
        side_effect=WhatsAppAPIError(400, '{"error": {"message": "Invalid phone"}}'),
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
async def test_whatsapp_reply_url_uses_config_phone_number_id(
    ac: AsyncClient, token: str
) -> None:
    """WhatsAppClient must be constructed with WHATSAPP_PHONE_NUMBER_ID from config."""
    conv_id = await _insert_whatsapp_conv()
    headers = {"Authorization": f"Bearer {token}"}

    captured_phone_number_id: list[str] = []
    original_init = __import__(
        "app.clients.whatsapp", fromlist=["WhatsAppClient"]
    ).WhatsAppClient.__init__

    def capturing_init(self, http, access_token, phone_number_id, api_version="v21.0"):
        captured_phone_number_id.append(phone_number_id)
        original_init(self, http, access_token, phone_number_id, api_version)

    with (
        patch(
            "app.clients.whatsapp.WhatsAppClient.__init__",
            new=capturing_init,
        ),
        patch(
            "app.clients.whatsapp.WhatsAppClient.send_text",
            new_callable=AsyncMock,
            return_value=_FAKE_WAMID,
        ),
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            json=_REPLY_BODY,
            headers=headers,
        )

    assert resp.status_code == 201
    assert captured_phone_number_id == [_ENV_OVERRIDES["WHATSAPP_PHONE_NUMBER_ID"]]
