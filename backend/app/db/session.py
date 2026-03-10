from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

# Module-level engine — created once on startup, disposed on shutdown
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> None:
    global _engine, _session_factory
    _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    assert _session_factory is not None, "DB engine not initialized"
    async with _session_factory() as session:
        yield session


@asynccontextmanager
async def worker_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for background workers (no FastAPI Depends)."""
    assert _session_factory is not None, "DB engine not initialized"
    async with _session_factory() as session:
        yield session


# Typed FastAPI dependency alias for use in route signatures
SessionDep = Annotated[AsyncSession, Depends(get_session)]
