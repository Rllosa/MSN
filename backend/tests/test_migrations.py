from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config
import asyncpg
import pytest


def _alembic_cfg(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _asyncpg_url(sqlalchemy_url: str) -> str:
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")


async def _table_names(url: str) -> set[str]:
    conn = await asyncpg.connect(_asyncpg_url(url))
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        return {row["tablename"] for row in rows}
    finally:
        await conn.close()


EXPECTED_TABLES = {"properties", "users", "conversations", "messages", "templates"}


@pytest.mark.asyncio
async def test_upgrade_creates_all_tables(clean_db: None, test_db_url: str) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_cfg(test_db_url), "head")
    tables = await _table_names(test_db_url)
    assert EXPECTED_TABLES.issubset(tables)


@pytest.mark.asyncio
async def test_downgrade_removes_all_tables(clean_db: None, test_db_url: str) -> None:
    await asyncio.to_thread(command.upgrade, _alembic_cfg(test_db_url), "head")
    await asyncio.to_thread(command.downgrade, _alembic_cfg(test_db_url), "base")
    tables = await _table_names(test_db_url)
    assert EXPECTED_TABLES.isdisjoint(tables)


@pytest.mark.asyncio
async def test_upgrade_idempotent(clean_db: None, test_db_url: str) -> None:
    # Running upgrade head twice must be a no-op; alembic_version prevents re-applying
    cfg = _alembic_cfg(test_db_url)
    await asyncio.to_thread(command.upgrade, cfg, "head")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    tables = await _table_names(test_db_url)
    assert EXPECTED_TABLES.issubset(tables)
