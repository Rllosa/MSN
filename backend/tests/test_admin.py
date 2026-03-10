"""Admin endpoint tests: list, create, delete, patch users.

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis

Uses the same migrated_db + client fixture pattern as test_auth.py.
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

_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASSWORD = "admin-password-123"
_USER_EMAIL = "user@example.com"
_USER_PASSWORD = "user-password-456"

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
    """AsyncClient with ASGI transport. Manually init/dispose DB + Redis."""
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
    """Insert an admin user directly via asyncpg; return user dict."""
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


@pytest_asyncio.fixture()
async def regular_user_in_db(migrated_db):
    """Insert a non-admin user directly via asyncpg; return user dict."""
    pw_hash = hash_password(_USER_PASSWORD)
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "INSERT INTO users (email, password_hash, is_active, is_admin)"
            " VALUES ($1, $2, TRUE, FALSE) RETURNING id::text",
            _USER_EMAIL,
            pw_hash,
        )
    finally:
        await conn.close()
    return {"id": row["id"], "email": _USER_EMAIL, "password": _USER_PASSWORD}


async def _login(client: AsyncClient, email: str, password: str) -> str:
    """Helper: login and return access token."""
    r = await client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_as_admin(admin_in_db, client):
    token = await _login(client, _ADMIN_EMAIL, _ADMIN_PASSWORD)
    r = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    users = r.json()
    assert any(u["email"] == _ADMIN_EMAIL and u["is_admin"] is True for u in users)


@pytest.mark.asyncio
async def test_list_users_as_non_admin(admin_in_db, regular_user_in_db, client):
    token = await _login(client, _USER_EMAIL, _USER_PASSWORD)
    r = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Admin access required"


@pytest.mark.asyncio
async def test_list_users_unauthenticated(client):
    r = await client.get("/api/admin/users")
    assert r.status_code == 403  # HTTPBearer returns 403 when header is missing


@pytest.mark.asyncio
async def test_create_user_as_admin(admin_in_db, client):
    token = await _login(client, _ADMIN_EMAIL, _ADMIN_PASSWORD)
    r = await client.post(
        "/api/admin/users",
        json={"email": "new@example.com", "password": "newpassword"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "new@example.com"
    assert body["is_admin"] is False
    assert body["is_active"] is True

    # New user can log in
    login_r = await client.post(
        "/api/auth/login",
        json={"email": "new@example.com", "password": "newpassword"},
    )
    assert login_r.status_code == 200


@pytest.mark.asyncio
async def test_create_user_duplicate_email(admin_in_db, client):
    token = await _login(client, _ADMIN_EMAIL, _ADMIN_PASSWORD)
    r = await client.post(
        "/api/admin/users",
        json={"email": _ADMIN_EMAIL, "password": "another"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Email already registered"


@pytest.mark.asyncio
async def test_delete_user_as_admin(admin_in_db, regular_user_in_db, client):
    token = await _login(client, _ADMIN_EMAIL, _ADMIN_PASSWORD)
    user_id = regular_user_in_db["id"]

    r = await client.delete(
        f"/api/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204

    # Deleted user cannot log in
    login_r = await client.post(
        "/api/auth/login",
        json={"email": _USER_EMAIL, "password": _USER_PASSWORD},
    )
    assert login_r.status_code == 401


@pytest.mark.asyncio
async def test_delete_last_admin_blocked(admin_in_db, client):
    token = await _login(client, _ADMIN_EMAIL, _ADMIN_PASSWORD)
    admin_id = admin_in_db["id"]

    r = await client.delete(
        f"/api/admin/users/{admin_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "Cannot delete the last admin"


@pytest.mark.asyncio
async def test_patch_user_password(admin_in_db, regular_user_in_db, client):
    token = await _login(client, _ADMIN_EMAIL, _ADMIN_PASSWORD)
    user_id = regular_user_in_db["id"]

    r = await client.patch(
        f"/api/admin/users/{user_id}",
        json={"password": "new-password-789"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    # Old password no longer works
    old_login = await client.post(
        "/api/auth/login",
        json={"email": _USER_EMAIL, "password": _USER_PASSWORD},
    )
    assert old_login.status_code == 401

    # New password works
    new_login = await client.post(
        "/api/auth/login",
        json={"email": _USER_EMAIL, "password": "new-password-789"},
    )
    assert new_login.status_code == 200


@pytest.mark.asyncio
async def test_patch_user_is_admin(admin_in_db, regular_user_in_db, client):
    token = await _login(client, _ADMIN_EMAIL, _ADMIN_PASSWORD)
    user_id = regular_user_in_db["id"]

    r = await client.patch(
        f"/api/admin/users/{user_id}",
        json={"is_admin": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["is_admin"] is True

    # Newly promoted user can access admin endpoints
    new_admin_token = await _login(client, _USER_EMAIL, _USER_PASSWORD)
    list_r = await client.get(
        "/api/admin/users",
        headers={"Authorization": f"Bearer {new_admin_token}"},
    )
    assert list_r.status_code == 200
