from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.router import router
from app.api.schemas import HealthResponse
from app.api.ws import pubsub_listener, websocket_endpoint
from app.db.redis import dispose_redis, init_redis
from app.db.session import dispose_engine, init_engine
from app.workers.beds24 import start_beds24_worker, stop_beds24_worker
from app.workers.imap import start_imap_worker, stop_imap_worker

_pubsub_task: asyncio.Task | None = None
_cleanup_task: asyncio.Task | None = None

_logger = logging.getLogger(__name__)
_ATTACHMENTS_DIR = Path(__file__).parent.parent / "media" / "attachments"
_MAX_AGE_SECONDS = 14 * 24 * 60 * 60  # 2 weeks
_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60  # run once a day


async def _attachment_cleanup_worker() -> None:
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        now = time.time()
        deleted = 0
        for f in _ATTACHMENTS_DIR.iterdir():
            if f.is_file() and (now - f.stat().st_mtime) > _MAX_AGE_SECONDS:
                f.unlink()
                deleted += 1
        if deleted:
            _logger.info("cleanup.attachments deleted=%d", deleted)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _pubsub_task, _cleanup_task
    init_engine()
    init_redis()
    start_imap_worker()
    start_beds24_worker()
    _pubsub_task = asyncio.create_task(pubsub_listener())
    _cleanup_task = asyncio.create_task(_attachment_cleanup_worker())
    yield
    await stop_imap_worker()
    await stop_beds24_worker()
    for task in (_pubsub_task, _cleanup_task):
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    await dispose_engine()
    await dispose_redis()


app = FastAPI(
    title="MSN Unified Messaging Dashboard",
    lifespan=lifespan,
)

_MEDIA_DIR = Path(__file__).parent.parent / "media"
_MEDIA_DIR.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_MEDIA_DIR)), name="media")

app.include_router(router, prefix="/api")
app.add_api_websocket_route("/ws", websocket_endpoint)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
