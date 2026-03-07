from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.api.schemas import HealthResponse
from app.db.redis import dispose_redis, init_redis
from app.db.session import dispose_engine, init_engine
from app.workers.imap import start_imap_worker, stop_imap_worker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_engine()
    init_redis()
    start_imap_worker()
    # TODO(SOLO-113): Start Redis pub/sub listener for WebSocket push
    yield
    await stop_imap_worker()
    await dispose_engine()
    await dispose_redis()


app = FastAPI(
    title="MSN Unified Messaging Dashboard",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
