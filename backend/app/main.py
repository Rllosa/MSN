from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.api.schemas import HealthResponse
from app.api.ws import pubsub_listener, websocket_endpoint
from app.db.redis import dispose_redis, init_redis
from app.db.session import dispose_engine, init_engine
from app.workers.beds24 import start_beds24_worker, stop_beds24_worker
from app.workers.imap import start_imap_worker, stop_imap_worker

_pubsub_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _pubsub_task
    init_engine()
    init_redis()
    start_imap_worker()
    start_beds24_worker()
    _pubsub_task = asyncio.create_task(pubsub_listener())
    yield
    await stop_imap_worker()
    await stop_beds24_worker()
    if _pubsub_task is not None:
        _pubsub_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _pubsub_task
    await dispose_engine()
    await dispose_redis()


app = FastAPI(
    title="MSN Unified Messaging Dashboard",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api")
app.add_api_websocket_route("/ws", websocket_endpoint)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
