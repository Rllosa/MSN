from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # TODO(SOLO-108): Start IMAP ingestion worker
    # TODO(SOLO-113): Start Redis pub/sub listener for WebSocket push
    yield
    # TODO(SOLO-108): Stop IMAP ingestion worker


app = FastAPI(
    title="MSN Unified Messaging Dashboard",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
