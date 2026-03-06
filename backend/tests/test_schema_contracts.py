"""Schema contract tests — golden-fixture assertions for every table.

Any deviation from the expected columns, types, constraints, or indexes
is a breaking change and must be caught here before it reaches production.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import asyncpg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _pg_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@asynccontextmanager
async def _db(url: str):
    conn = await asyncpg.connect(_pg_url(url))
    try:
        yield conn
    finally:
        await conn.close()


async def _columns(conn: asyncpg.Connection, table: str) -> dict:
    """Return {column_name: {type, nullable}} for a table."""
    rows = await conn.fetch(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        ORDER BY ordinal_position
        """,
        table,
    )
    return {
        r["column_name"]: {
            "type": r["data_type"],
            "nullable": r["is_nullable"] == "YES",
        }
        for r in rows
    }


async def _unique_constraints(conn: asyncpg.Connection, table: str) -> dict:
    """Return {constraint_name: [column_names]} for UNIQUE constraints."""
    rows = await conn.fetch(
        """
        SELECT tc.constraint_name, kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.table_name = $1
          AND tc.constraint_type = 'UNIQUE'
        ORDER BY tc.constraint_name, kcu.ordinal_position
        """,
        table,
    )
    result: dict = {}
    for r in rows:
        result.setdefault(r["constraint_name"], []).append(r["column_name"])
    return result


async def _fk_targets(conn: asyncpg.Connection, table: str) -> dict:
    """Return {fk_name: 'foreign_table.foreign_col'} for all FKs on a table."""
    rows = await conn.fetch(
        """
        SELECT tc.constraint_name,
               ccu.table_name  AS foreign_table,
               ccu.column_name AS foreign_col
        FROM information_schema.table_constraints tc
        JOIN information_schema.referential_constraints rc
            ON tc.constraint_name = rc.constraint_name
        JOIN information_schema.constraint_column_usage ccu
            ON rc.unique_constraint_name = ccu.constraint_name
        WHERE tc.table_schema = 'public' AND tc.table_name = $1
        """,
        table,
    )
    return {
        r["constraint_name"]: f"{r['foreign_table']}.{r['foreign_col']}" for r in rows
    }


async def _indexes(conn: asyncpg.Connection, table: str) -> set:
    """Return the set of index names for a table."""
    rows = await conn.fetch(
        "SELECT indexname FROM pg_indexes"
        " WHERE schemaname = 'public' AND tablename = $1",
        table,
    )
    return {r["indexname"] for r in rows}


# ---------------------------------------------------------------------------
# Fixture — clean DB + migration applied once per test
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def migrated_db(clean_db: None, test_db_url: str) -> str:
    """Reset schema via clean_db then apply migration. Read-only tests follow."""
    await asyncio.to_thread(command.upgrade, _alembic_cfg(test_db_url), "head")
    return test_db_url


# ---------------------------------------------------------------------------
# Enum contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_platform_enum_values(migrated_db: str) -> None:
    async with _db(migrated_db) as conn:
        rows = await conn.fetch(
            """
            SELECT e.enumlabel
            FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid
            WHERE t.typname = 'platform_enum'
            ORDER BY e.enumsortorder
            """,
        )
    assert [r["enumlabel"] for r in rows] == ["airbnb", "booking", "whatsapp"]


@pytest.mark.asyncio
async def test_direction_enum_values(migrated_db: str) -> None:
    async with _db(migrated_db) as conn:
        rows = await conn.fetch(
            """
            SELECT e.enumlabel
            FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid
            WHERE t.typname = 'direction_enum'
            ORDER BY e.enumsortorder
            """,
        )
    assert [r["enumlabel"] for r in rows] == ["inbound", "outbound"]


# ---------------------------------------------------------------------------
# Table schema contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_properties_schema(migrated_db: str) -> None:
    async with _db(migrated_db) as conn:
        cols = await _columns(conn, "properties")
        uqs = await _unique_constraints(conn, "properties")
        idxs = await _indexes(conn, "properties")

    assert cols["id"] == {"type": "uuid", "nullable": False}
    assert cols["name"] == {"type": "character varying", "nullable": False}
    assert cols["slug"] == {"type": "character varying", "nullable": False}
    assert cols["created_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
    assert "uq_properties_slug" in uqs
    assert uqs["uq_properties_slug"] == ["slug"]
    assert any("pkey" in idx for idx in idxs)


@pytest.mark.asyncio
async def test_users_schema(migrated_db: str) -> None:
    async with _db(migrated_db) as conn:
        cols = await _columns(conn, "users")
        uqs = await _unique_constraints(conn, "users")

    assert cols["id"] == {"type": "uuid", "nullable": False}
    assert cols["email"] == {"type": "character varying", "nullable": False}
    assert cols["password_hash"] == {"type": "character varying", "nullable": False}
    assert cols["is_active"] == {"type": "boolean", "nullable": False}
    assert cols["created_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
    assert "uq_users_email" in uqs
    assert uqs["uq_users_email"] == ["email"]


@pytest.mark.asyncio
async def test_conversations_schema(migrated_db: str) -> None:
    async with _db(migrated_db) as conn:
        cols = await _columns(conn, "conversations")
        fks = await _fk_targets(conn, "conversations")
        idxs = await _indexes(conn, "conversations")

    assert cols["id"] == {"type": "uuid", "nullable": False}
    # platform uses a PostgreSQL user-defined enum type
    assert cols["platform"] == {"type": "USER-DEFINED", "nullable": False}
    assert cols["guest_name"] == {"type": "character varying", "nullable": False}
    assert cols["guest_contact"]["nullable"] is True
    assert cols["property_id"]["nullable"] is True
    assert cols["external_url"]["nullable"] is True
    assert cols["last_message_at"]["nullable"] is True
    assert cols["created_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
    assert cols["updated_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
    assert fks.get("fk_conversations_property_id") == "properties.id"
    assert "ix_conversations_property_last_message" in idxs
    assert "ix_conversations_platform_last_message" in idxs


@pytest.mark.asyncio
async def test_messages_schema(migrated_db: str) -> None:
    async with _db(migrated_db) as conn:
        cols = await _columns(conn, "messages")
        uqs = await _unique_constraints(conn, "messages")
        fks = await _fk_targets(conn, "messages")
        idxs = await _indexes(conn, "messages")

    assert cols["id"] == {"type": "uuid", "nullable": False}
    assert cols["conversation_id"] == {"type": "uuid", "nullable": False}
    assert cols["message_id_hash"] == {"type": "character varying", "nullable": False}
    # direction uses a PostgreSQL user-defined enum type
    assert cols["direction"] == {"type": "USER-DEFINED", "nullable": False}
    assert cols["body"] == {"type": "text", "nullable": False}
    assert cols["sent_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
    assert cols["created_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
    assert cols["raw_headers"] == {"type": "jsonb", "nullable": True}
    assert "uq_messages_message_id_hash" in uqs
    assert uqs["uq_messages_message_id_hash"] == ["message_id_hash"]
    assert fks.get("fk_messages_conversation_id") == "conversations.id"
    assert "ix_messages_conversation_sent_at" in idxs


@pytest.mark.asyncio
async def test_templates_schema(migrated_db: str) -> None:
    async with _db(migrated_db) as conn:
        cols = await _columns(conn, "templates")

    assert cols["id"] == {"type": "uuid", "nullable": False}
    assert cols["name"] == {"type": "character varying", "nullable": False}
    assert cols["content"] == {"type": "text", "nullable": False}
    # platform_scope and trigger_keywords are VARCHAR[] arrays
    assert cols["platform_scope"] == {"type": "ARRAY", "nullable": False}
    assert cols["trigger_keywords"] == {"type": "ARRAY", "nullable": False}
    assert cols["created_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
    assert cols["updated_at"] == {
        "type": "timestamp with time zone",
        "nullable": False,
    }
