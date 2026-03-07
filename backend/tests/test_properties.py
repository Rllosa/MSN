"""Properties endpoint tests: list, create, patch, delete + seed script idempotency.

Requires live PostgreSQL (port 5433) + Redis (port 6380) from:
    docker compose up -d postgres redis
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
    """Insert an admin user directly via asyncpg."""
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


async def _admin_token(client: AsyncClient) -> str:
    r = await client.post(
        "/api/auth/login",
        json={"email": _ADMIN_EMAIL, "password": _ADMIN_PASSWORD},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_properties_authenticated(admin_in_db, client):
    token = await _admin_token(client)
    r = await client.get(
        "/api/properties/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json() == []  # empty initially


@pytest.mark.asyncio
async def test_list_properties_unauthenticated(client):
    r = await client.get("/api/properties/")
    assert r.status_code == 403  # HTTPBearer returns 403 when header absent


@pytest.mark.asyncio
async def test_create_property_as_admin(admin_in_db, client):
    token = await _admin_token(client)
    r = await client.post(
        "/api/properties/",
        json={"name": "Villa Palm Beach"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Villa Palm Beach"
    assert body["slug"] == "villa-palm-beach"  # auto-generated

    # Property appears in list
    list_r = await client.get(
        "/api/properties/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert any(p["slug"] == "villa-palm-beach" for p in list_r.json())


@pytest.mark.asyncio
async def test_create_property_duplicate_slug(admin_in_db, client):
    token = await _admin_token(client)
    await client.post(
        "/api/properties/",
        json={"name": "Villa 1", "slug": "villa-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    r = await client.post(
        "/api/properties/",
        json={"name": "Another Villa", "slug": "villa-1"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Slug already exists"


@pytest.mark.asyncio
async def test_patch_property_name(admin_in_db, client):
    token = await _admin_token(client)
    create_r = await client.post(
        "/api/properties/",
        json={"name": "Old Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_r.status_code == 201
    prop_id = create_r.json()["id"]

    r = await client.patch(
        f"/api/properties/{prop_id}",
        json={"name": "New Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"
    assert r.json()["slug"] == "new-name"  # re-slugified


@pytest.mark.asyncio
async def test_delete_property_no_conversations(admin_in_db, client):
    token = await _admin_token(client)
    create_r = await client.post(
        "/api/properties/",
        json={"name": "Villa Delete Me"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_r.status_code == 201
    prop_id = create_r.json()["id"]

    r = await client.delete(
        f"/api/properties/{prop_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 204

    # Property no longer in list
    list_r = await client.get(
        "/api/properties/",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert not any(p["id"] == prop_id for p in list_r.json())


@pytest.mark.asyncio
async def test_delete_property_with_conversations(admin_in_db, client):
    token = await _admin_token(client)
    create_r = await client.post(
        "/api/properties/",
        json={"name": "Busy Villa"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_r.status_code == 201
    prop_id = create_r.json()["id"]

    # Insert a conversation referencing this property via asyncpg
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await conn.execute(
            "INSERT INTO conversations"
            " (platform, guest_name, property_id, created_at, updated_at)"
            " VALUES ('airbnb', 'Test Guest', $1, NOW(), NOW())",
            prop_id,
        )
    finally:
        await conn.close()

    r = await client.delete(
        f"/api/properties/{prop_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Property has active conversations"


@pytest.mark.asyncio
async def test_seed_script_idempotent(migrated_db):
    """Seed script inserts 7 rows; running twice yields exactly 7 rows."""
    import os

    os.environ["TEST_DATABASE_URL"] = _DB_URL

    from scripts.seed_properties import main as seed_main

    await seed_main()
    await seed_main()  # second run — must be idempotent

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM properties")
    finally:
        await conn.close()

    assert count == 7
