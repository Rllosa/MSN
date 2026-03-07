"""Auth endpoint tests: login, refresh, logout, /me.

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis

Uses httpx.AsyncClient with ASGI transport so the full FastAPI lifespan runs per test.
"""

from __future__ import annotations

import asyncio
import os

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

_TEST_EMAIL = "test@example.com"
_TEST_PASSWORD = "correct-horse-battery"

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
}


def _asyncpg_dsn() -> str:
    return _DB_URL.replace("postgresql+asyncpg://", "postgresql://")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def migrated_db(monkeypatch):
    """Set env vars, clear settings cache, reset DB schema, run migrations."""
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
    """AsyncClient with ASGI transport. Manually init/dispose DB + Redis because
    httpx ASGITransport does not trigger the FastAPI lifespan."""
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
async def user_in_db(migrated_db):
    """Insert one active test user directly via asyncpg; return user dict."""
    pw_hash = hash_password(_TEST_PASSWORD)
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "INSERT INTO users (email, password_hash, is_active)"
            " VALUES ($1, $2, TRUE) RETURNING id::text",
            _TEST_EMAIL,
            pw_hash,
        )
    finally:
        await conn.close()
    return {"id": row["id"], "email": _TEST_EMAIL, "password": _TEST_PASSWORD}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(user_in_db, client):
    r = await client.post(
        "/api/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert "refresh_token" in r.cookies


@pytest.mark.asyncio
async def test_login_wrong_password(user_in_db, client):
    r = await client.post(
        "/api/auth/login",
        json={"email": _TEST_EMAIL, "password": "wrong"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_login_unknown_email(user_in_db, client):
    r = await client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": _TEST_PASSWORD},
    )
    assert r.status_code == 401
    # Same message as wrong password — prevents email enumeration
    assert r.json()["detail"] == "Invalid credentials"


@pytest.mark.asyncio
async def test_login_inactive_user(client):
    pw_hash = hash_password(_TEST_PASSWORD)
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await conn.execute(
            "INSERT INTO users (email, password_hash, is_active)"
            " VALUES ($1, $2, FALSE)",
            "inactive@example.com",
            pw_hash,
        )
    finally:
        await conn.close()

    r = await client.post(
        "/api/auth/login",
        json={"email": "inactive@example.com", "password": _TEST_PASSWORD},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Account disabled"


@pytest.mark.asyncio
async def test_refresh_valid_cookie(user_in_db, client):
    login = await client.post(
        "/api/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    assert login.status_code == 200

    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200
    assert "access_token" in r.json()


@pytest.mark.asyncio
async def test_refresh_missing_cookie(client):
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 401
    assert r.json()["detail"] == "Missing refresh token"


@pytest.mark.asyncio
async def test_refresh_revoked_token(user_in_db, client):
    login = await client.post(
        "/api/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    assert login.status_code == 200

    logout = await client.post("/api/auth/logout")
    assert logout.status_code == 204

    r = await client.post("/api/auth/refresh")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_logout_clears_cookie(user_in_db, client):
    login = await client.post(
        "/api/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    assert login.status_code == 200

    r = await client.post("/api/auth/logout")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_me_authenticated(user_in_db, client):
    login = await client.post(
        "/api/auth/login",
        json={"email": _TEST_EMAIL, "password": _TEST_PASSWORD},
    )
    access_token = login.json()["access_token"]

    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == _TEST_EMAIL
    assert body["id"] == user_in_db["id"]
    assert body["is_active"] is True
