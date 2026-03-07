from __future__ import annotations

from fastapi import APIRouter

from app.api.auth import router as auth_router

router = APIRouter()
router.include_router(auth_router)

# TODO(SOLO-107): properties routes (/properties)
# TODO(SOLO-112): conversations + messages routes (/conversations, /messages)
