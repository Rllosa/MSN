"""WebSocket endpoint tests.

Uses Starlette's synchronous TestClient for WebSocket testing — no extra deps.

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import asyncpg
import pytest

from alembic import command
from alembic.config import Config
from app.auth.tokens import create_access_token

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
# Fixtures — synchronous so TestClient (sync) can use them without event loop
# conflicts. asyncpg setup runs via asyncio.run() before any loop is created.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def migrated_db():
    """Reset schema and run migrations against the test DB (sync fixture)."""

    async def _setup() -> None:
        conn = await asyncpg.connect(_asyncpg_dsn())
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        await conn.close()

    with patch.dict("os.environ", _ENV_OVERRIDES):
        asyncio.run(_setup())

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", _DB_URL)
        command.upgrade(cfg, "head")
    yield


@pytest.fixture
def ws_client(migrated_db):
    """Synchronous Starlette TestClient with WebSocket support."""
    with patch.dict("os.environ", _ENV_OVERRIDES):
        from app.config import get_settings

        get_settings.cache_clear()
        from starlette.testclient import TestClient

        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(user_id: str | None = None) -> str:
    uid = user_id or str(uuid.uuid4())
    with patch.dict("os.environ", _ENV_OVERRIDES):
        from app.config import get_settings

        get_settings.cache_clear()
        return create_access_token(uid, "user@example.com")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ws_valid_auth(ws_client):
    """Valid JWT in auth message → connection accepted, stays open."""
    token = _make_token()

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        # No exception raised = connection accepted and alive


def test_ws_invalid_token(ws_client):
    """Invalid JWT → server closes with code 4001."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises((WebSocketDisconnect, Exception)):
        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "auth", "token": "not.a.valid.token"})
            ws.receive_text()  # raises because server closed with 4001


def test_ws_broadcast_delivers_message(ws_client):
    """Redis publish → pubsub_listener → WS client receives the event."""
    import time

    import redis as _redis

    token = _make_token()
    payload = json.dumps(
        {
            "type": "new_message",
            "conversation_id": str(uuid.uuid4()),
            "message": {"id": str(uuid.uuid4()), "body": "Hello guest"},
        }
    )

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": token})
        # Publish via sync Redis client — pubsub_listener forwards to WS
        r = _redis.Redis.from_url(_REDIS_URL, decode_responses=True)
        r.publish("msn:new_message", payload)
        r.close()
        time.sleep(0.2)  # let pubsub_listener process
        received = ws.receive_text()

    data = json.loads(received)
    assert data["type"] == "new_message"
    assert data["message"]["body"] == "Hello guest"


@pytest.mark.asyncio
async def test_ws_publish_redis_down_does_not_raise():
    """_try_publish() with Redis unavailable logs a warning but never raises."""
    from app.db.ingest import _try_publish

    # get_redis is lazy-imported inside _try_publish from app.db.redis,
    # so we patch the source module.
    with patch("app.db.redis.get_redis", side_effect=Exception("Redis down")):
        await _try_publish(
            conversation_id=str(uuid.uuid4()),
            message_id=str(uuid.uuid4()),
            direction="inbound",
            body="test body",
            sent_at=datetime.now(UTC),
        )
