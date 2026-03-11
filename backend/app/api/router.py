from __future__ import annotations

from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.properties import router as properties_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_router)
router.include_router(properties_router)
router.include_router(conversations_router)

# TODO(SOLO-106): wire admin panel frontend in SOLO-114
