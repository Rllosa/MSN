from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio


def _sqlalchemy_url() -> str:
    return os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://msn:msn@localhost:5432/msn_test",
    )


def _asyncpg_url(sqlalchemy_url: str) -> str:
    # asyncpg.connect() does not accept the +asyncpg driver prefix
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="session")
def test_db_url() -> str:
    return _sqlalchemy_url()


@pytest_asyncio.fixture()
async def clean_db(test_db_url: str) -> None:
    """Drop and recreate the public schema to give each migration test a clean slate."""
    conn = await asyncpg.connect(_asyncpg_url(test_db_url))
    try:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.execute("CREATE SCHEMA public")
        await conn.execute("DROP TYPE IF EXISTS platform_enum CASCADE")
        await conn.execute("DROP TYPE IF EXISTS direction_enum CASCADE")
    finally:
        await conn.close()
