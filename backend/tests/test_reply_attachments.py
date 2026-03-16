"""Integration tests for image attachments in POST /conversations/{id}/reply.

Covers SOLO-141 — all three send channels (Beds24, SMTP, WhatsApp) plus
validation edge cases.

Requires live PostgreSQL (port 5433) + Redis (port 6380):
    docker compose up -d postgres redis
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
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

_ADMIN_EMAIL = "attach-test@example.com"
_ADMIN_PASSWORD = "attach-password-123"

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

# Minimal valid 1×1 PNG (67 bytes)
_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
_PNG_MIME = "image/png"
_REPLY_TEXT = "Here is the photo you requested."


def _asyncpg_dsn() -> str:
    return _DB_URL.replace("postgresql+asyncpg://", "postgresql://")


# ---------------------------------------------------------------------------
# Fixtures (same pattern as test_reply.py)
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
async def test_reply_image_only_beds24(ac: AsyncClient, token: str) -> None:
    """Image with no text via Beds24 — message stored with <img> body only."""
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
            return_value=99100,
        ) as mock_post,
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            files={"file": ("photo.png", _PNG_BYTES, _PNG_MIME)},
            headers=headers,
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["direction"] == "outbound"
    assert "<img" in data["body"]
    assert "/media/attachments/" in data["body"]
    # Beds24 post_message called with attachment bytes (no text)
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["attachment"] == _PNG_BYTES
    assert call_kwargs["attachment_mime_type"] == _PNG_MIME
    assert call_kwargs["message"] == ""


@pytest.mark.asyncio
async def test_reply_image_and_text_beds24(ac: AsyncClient, token: str) -> None:
    """Image + text via Beds24 — body contains both img tag and text."""
    conv_id = await _insert_conv("airbnb", "82940751")
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
            return_value=99101,
        ) as mock_post,
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            data={"content": _REPLY_TEXT},
            files={"file": ("photo.png", _PNG_BYTES, _PNG_MIME)},
            headers=headers,
        )

    assert resp.status_code == 201
    body = resp.json()["body"]
    assert "<img" in body
    assert _REPLY_TEXT in body
    assert mock_post.call_args.kwargs["message"] == _REPLY_TEXT


@pytest.mark.asyncio
async def test_reply_image_smtp(ac: AsyncClient, token: str) -> None:
    """Image via SMTP — aiosmtplib.send called with attachment bytes."""
    conv_id = await _insert_conv("airbnb", "TOKEN123abc@reply.airbnb.com")
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.clients.smtp.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            data={"content": _REPLY_TEXT},
            files={"file": ("photo.png", _PNG_BYTES, _PNG_MIME)},
            headers=headers,
        )

    assert resp.status_code == 201
    mock_send.assert_awaited_once()
    sent_msg = mock_send.call_args.args[0]
    # MIMEMultipart — verify attachment payload exists
    payloads = list(sent_msg.iter_attachments())
    assert len(payloads) == 1
    assert payloads[0].get_content_type() == _PNG_MIME


@pytest.mark.asyncio
async def test_reply_image_whatsapp(ac: AsyncClient, token: str) -> None:
    """Image via WhatsApp — upload_media then send_image called."""
    conv_id = await _insert_conv("whatsapp", "33612345678")
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch(
            "app.api.conversations.WhatsAppClient.upload_media",
            new_callable=AsyncMock,
            return_value="fake_media_id_001",
        ) as mock_upload,
        patch(
            "app.api.conversations.WhatsAppClient.send_image",
            new_callable=AsyncMock,
            return_value="wamid.fake001",
        ) as mock_send,
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            data={"content": _REPLY_TEXT},
            files={"file": ("photo.png", _PNG_BYTES, _PNG_MIME)},
            headers=headers,
        )

    assert resp.status_code == 201
    mock_upload.assert_awaited_once_with(_PNG_BYTES, _PNG_MIME, "photo.png")
    mock_send.assert_awaited_once_with(
        "33612345678", "fake_media_id_001", caption=_REPLY_TEXT
    )


@pytest.mark.asyncio
async def test_reply_file_too_large_returns_422(ac: AsyncClient, token: str) -> None:
    """File exceeding 5 MB returns 422."""
    conv_id = await _insert_conv("airbnb", "82940753")
    headers = {"Authorization": f"Bearer {token}"}
    big_file = b"x" * (5 * 1024 * 1024 + 1)

    resp = await ac.post(
        f"/api/conversations/{conv_id}/reply",
        files={"file": ("big.jpg", big_file, "image/jpeg")},
        headers=headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reply_invalid_mime_type_returns_422(ac: AsyncClient, token: str) -> None:
    """Non-image MIME type returns 422."""
    conv_id = await _insert_conv("airbnb", "82940754")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await ac.post(
        f"/api/conversations/{conv_id}/reply",
        files={"file": ("doc.pdf", b"%PDF", "application/pdf")},
        headers=headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reply_no_content_no_file_returns_422(
    ac: AsyncClient, token: str
) -> None:
    """Neither content nor file → 422."""
    conv_id = await _insert_conv("airbnb", "82940755")
    headers = {"Authorization": f"Bearer {token}"}

    resp = await ac.post(
        f"/api/conversations/{conv_id}/reply",
        data={"content": ""},
        headers=headers,
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_reply_file_cleaned_up_on_send_failure(
    ac: AsyncClient, token: str
) -> None:
    """If the send fails the locally saved attachment file is deleted."""
    conv_id = await _insert_conv("airbnb", "82940756")
    headers = {"Authorization": f"Bearer {token}"}

    saved_paths: list[Path] = []

    original_write = Path.write_bytes

    def _capture_write(self: Path, data: bytes) -> None:
        if "attachments" in str(self):
            saved_paths.append(self)
        return original_write(self, data)

    with (
        patch.object(Path, "write_bytes", _capture_write),
        patch(
            "app.api.conversations.Beds24Client.authenticate",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.api.conversations.Beds24Client.post_message",
            new_callable=AsyncMock,
            side_effect=Exception("Beds24 connection refused"),
        ),
    ):
        resp = await ac.post(
            f"/api/conversations/{conv_id}/reply",
            files={"file": ("photo.png", _PNG_BYTES, _PNG_MIME)},
            headers=headers,
        )

    assert resp.status_code == 502
    # Every file saved during this request must have been deleted
    for p in saved_paths:
        assert not p.exists(), f"File {p} was not cleaned up after failure"
