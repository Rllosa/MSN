from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.api.schemas import HealthResponse
from app.db.session import dispose_engine, init_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    init_engine()
    # TODO(SOLO-108): Start IMAP ingestion worker
    # TODO(SOLO-113): Start Redis pub/sub listener for WebSocket push
    yield
    # TODO(SOLO-108): Stop IMAP ingestion worker
    await dispose_engine()


app = FastAPI(
    title="MSN Unified Messaging Dashboard",
    lifespan=lifespan,
)

app.include_router(router, prefix="/api")


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")
