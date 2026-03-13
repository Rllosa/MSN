"""WebSocket endpoint — real-time push of new messages to connected clients.

Auth flow (Decision 2B):
  1. Server accepts the raw connection.
  2. Client sends first message: {"type": "auth", "token": "<access_token>"}
  3. Server validates JWT. On failure: close(4001). On success: register + keep alive.

Connection registry (Decision 3B):
  dict[user_id, list[WebSocket]] — supports multiple tabs per user.

Redis pub/sub (Decision 1A):
  Single channel "msn:new_message". All connected clients receive all events.
  If Redis fails: log error, WS connections stay alive (Decision 4A).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect
import jwt

from app.auth.tokens import decode_token

logger = logging.getLogger(__name__)

_REDIS_CHANNEL = "msn:new_message"
_AUTH_TIMEOUT_S = 10.0


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Per-user registry of active WebSocket connections."""

    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    def register(self, websocket: WebSocket, user_id: str) -> None:
        self._connections[user_id].append(websocket)
        logger.info(
            "ws.registered user_id=%s total_connections=%d",
            user_id,
            self._total(),
        )

    def unregister(self, websocket: WebSocket, user_id: str) -> None:
        conns = self._connections.get(user_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(user_id, None)
        logger.info(
            "ws.unregistered user_id=%s total_connections=%d",
            user_id,
            self._total(),
        )

    async def broadcast(self, data: str) -> None:
        """Send a JSON string to all connected clients. Cleans up dead sockets."""
        dead: list[tuple[str, WebSocket]] = []
        for user_id, conns in list(self._connections.items()):
            for ws in list(conns):
                try:
                    await ws.send_text(data)
                except Exception:
                    dead.append((user_id, ws))
        for user_id, ws in dead:
            self.unregister(ws, user_id)

    def _total(self) -> int:
        return sum(len(v) for v in self._connections.values())


# Module-level singleton — shared by endpoint and pubsub_listener
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


async def websocket_endpoint(websocket: WebSocket) -> None:
    """Accept connection, authenticate via first message, then keep alive."""
    await websocket.accept()

    # --- Auth handshake ---
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=_AUTH_TIMEOUT_S)
        auth_msg = json.loads(raw)
    except Exception:
        await websocket.close(code=4001)
        return

    if auth_msg.get("type") != "auth":
        await websocket.close(code=4001)
        return

    token = auth_msg.get("token", "")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise jwt.PyJWTError("not an access token")
    except jwt.PyJWTError:
        logger.debug("ws.auth_rejected reason=invalid_token")
        await websocket.close(code=4001)
        return

    user_id: str = payload["sub"]
    manager.register(websocket, user_id)

    # --- Keep connection alive until client disconnects ---
    try:
        while True:
            # Drain any unexpected client messages; we don't act on them
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.unregister(websocket, user_id)


# ---------------------------------------------------------------------------
# Redis pub/sub listener (started as background task in lifespan)
# ---------------------------------------------------------------------------


async def pubsub_listener() -> None:
    """Subscribe to Redis and forward events to all connected WS clients.

    On Redis failure: logs the error and exits the task.
    WS connections remain alive — frontend falls back to REST polling (Rule 1.3).
    """
    from app.db.redis import get_redis

    redis = get_redis()
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(_REDIS_CHANNEL)
        logger.info("ws.pubsub_subscribed channel=%s", _REDIS_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            await manager.broadcast(message["data"])
    except asyncio.CancelledError:
        raise  # propagate cancellation for clean shutdown
    except Exception:
        logger.error("ws.pubsub_listener_error", exc_info=True)
    finally:
        try:
            await pubsub.aclose()
        except Exception:
            pass
