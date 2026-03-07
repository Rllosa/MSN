from __future__ import annotations

from redis.asyncio import Redis

_redis: Redis | None = None


def init_redis() -> None:
    from app.config import get_settings

    global _redis
    _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)


async def dispose_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


def get_redis() -> Redis:
    assert _redis is not None, "Redis not initialized"
    return _redis
