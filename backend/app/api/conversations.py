"""Conversations and messages REST API.

GET   /conversations              — paginated inbox, filterable
GET   /conversations/{id}         — conversation detail + last 50 messages
PATCH /conversations/{id}         — archive/unarchive or mark read
GET   /conversations/{id}/messages — cursor-based message history
POST  /conversations/{id}/reply   — send outbound reply (Airbnb only)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth.dependencies import CurrentUser
from app.clients.beds24 import Beds24Client
from app.clients.smtp import send_smtp_reply
from app.config import get_settings
from app.db.session import SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/conversations", tags=["conversations"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class MessageOut(BaseModel):
    id: str
    direction: str
    body: str
    sent_at: datetime
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    platform: str
    guest_name: str
    guest_contact: str | None
    property_id: str | None
    property_name: str | None
    status: str
    unread_count: int
    last_message_at: datetime | None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[MessageOut]


class ConversationsPage(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int


class MessagesPage(BaseModel):
    items: list[MessageOut]
    has_more: bool


class PatchConversationRequest(BaseModel):
    status: Literal["active", "archived"] | None = None
    mark_read: bool | None = None


class ReplyRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


# ---------------------------------------------------------------------------
# Pre-built SQL fragments (Rule 16.5 — static parts hoisted, WHERE is dynamic)
# ---------------------------------------------------------------------------

# Fixed SELECT + FROM used in both list and detail queries
_CONV_SELECT = """\
    SELECT
        c.id::text,
        c.platform::text,
        c.guest_name,
        c.guest_contact,
        c.property_id::text,
        p.name AS property_name,
        c.status,
        c.unread_count,
        c.last_message_at,
        c.created_at
    FROM conversations c
    LEFT JOIN properties p ON c.property_id = p.id"""

# Fixed ORDER + pagination used in the list query
_CONV_ORDER = (
    " ORDER BY c.last_message_at DESC NULLS LAST" " LIMIT :limit OFFSET :offset"
)

_SQL_CONV_BY_ID = text(
    f"{_CONV_SELECT} WHERE c.id = :conv_id"  # noqa: S608
)

_SQL_LAST_MESSAGES = text("""
    SELECT id::text, direction::text, body, sent_at, created_at
    FROM messages
    WHERE conversation_id = :conv_id
    ORDER BY sent_at ASC,
             (raw_headers->>'beds24_message_id')::bigint DESC NULLS LAST,
             created_at ASC
    LIMIT 50
""")

_SQL_MESSAGES_WITH_CURSOR = text("""
    SELECT id::text, direction::text, body, sent_at, created_at
    FROM messages
    WHERE conversation_id = :conv_id
      AND sent_at < :before
    ORDER BY sent_at DESC,
             (raw_headers->>'beds24_message_id')::bigint ASC NULLS LAST,
             created_at DESC
    LIMIT 51
""")

_SQL_MESSAGES_NO_CURSOR = text("""
    SELECT id::text, direction::text, body, sent_at, created_at
    FROM messages
    WHERE conversation_id = :conv_id
    ORDER BY sent_at DESC,
             (raw_headers->>'beds24_message_id')::bigint ASC NULLS LAST,
             created_at DESC
    LIMIT 51
""")

_SQL_MARK_READ = text(
    "UPDATE conversations"
    " SET unread_count = 0, updated_at = NOW()"
    " WHERE id = :conv_id"
)

_SQL_UPDATE_STATUS = text(
    "UPDATE conversations"
    " SET status = :status, updated_at = NOW()"
    " WHERE id = :conv_id"
)

_SQL_CONV_EXISTS = text("SELECT id FROM conversations WHERE id = :conv_id")

_SQL_CONV_FOR_REPLY = text(
    "SELECT platform::text, guest_contact FROM conversations WHERE id = :conv_id"
)

_SQL_BEDS24_TOKEN = text(
    "SELECT value FROM api_credentials WHERE key = 'beds24_refresh_token'"
)

_SQL_INSERT_REPLY = text("""
    INSERT INTO messages
        (conversation_id, message_id_hash, direction, body,
         sent_at, raw_headers, created_at)
    VALUES
        (:conv_id, :hash, 'outbound', :body,
         :sent_at, CAST(:raw_headers AS jsonb), NOW())
    RETURNING id::text
""")

_SQL_BUMP_LAST_MESSAGE = text(
    "UPDATE conversations"
    " SET last_message_at = :sent_at, updated_at = NOW()"
    " WHERE id = :conv_id"
)


# ---------------------------------------------------------------------------
# Dynamic WHERE builder — WHERE content varies per request, values parameterized
# ---------------------------------------------------------------------------


def _build_where(
    platforms: list[str] | None,
    property_ids: list[str] | None,
    conv_status: str | None,
    search: str | None,
    unread_only: bool = False,
) -> tuple[str, dict]:
    """Return (where_clause_sql, params) for the conversations list query.

    All user-supplied values are bound as named parameters — no injection risk.
    Only internal column names and our own placeholder keys appear in the SQL string.
    """
    clauses: list[str] = []
    params: dict = {}

    # Default to active-only inbox when no status filter is supplied
    if conv_status is not None:
        clauses.append("c.status = :status")
        params["status"] = conv_status
    else:
        clauses.append("c.status = 'active'")

    if platforms:
        ph = ", ".join(f":plat{i}" for i in range(len(platforms)))
        clauses.append(f"c.platform::text IN ({ph})")
        for i, p in enumerate(platforms):
            params[f"plat{i}"] = p

    if property_ids:
        # Named placeholders for each ID avoids array binding complexity
        ph = ", ".join(f":prop{i}" for i in range(len(property_ids)))
        clauses.append(f"c.property_id::text IN ({ph})")  # noqa: S608
        for i, pid in enumerate(property_ids):
            params[f"prop{i}"] = pid

    if search is not None:
        clauses.append("(c.guest_name ILIKE :search OR c.guest_contact ILIKE :search)")
        params["search"] = f"%{search}%"

    if unread_only:
        clauses.append("c.unread_count > 0")

    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, params


# ---------------------------------------------------------------------------
# Row mappers
# ---------------------------------------------------------------------------


def _to_summary(row) -> ConversationSummary:  # type: ignore[no-untyped-def]
    return ConversationSummary(
        id=row.id,
        platform=row.platform,
        guest_name=row.guest_name,
        guest_contact=row.guest_contact,
        property_id=row.property_id,
        property_name=row.property_name,
        status=row.status,
        unread_count=row.unread_count,
        last_message_at=row.last_message_at,
        created_at=row.created_at,
    )


def _to_message(row) -> MessageOut:  # type: ignore[no-untyped-def]
    return MessageOut(
        id=row.id,
        direction=row.direction,
        body=row.body,
        sent_at=row.sent_at,
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=ConversationsPage)
async def list_conversations(
    _: CurrentUser,
    session: SessionDep,
    platform: Annotated[str | None, Query()] = None,
    property_id: Annotated[str | None, Query()] = None,
    conv_status: Annotated[
        Literal["active", "archived"] | None, Query(alias="status")
    ] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    unread_only: Annotated[bool, Query(alias="unread_only")] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationsPage:
    platforms = (
        [p.strip() for p in platform.split(",") if p.strip()] if platform else None
    )
    property_ids = (
        [p.strip() for p in property_id.split(",") if p.strip()]
        if property_id
        else None
    )
    where, params = _build_where(
        platforms, property_ids, conv_status, search, unread_only
    )

    total: int = (
        await session.execute(
            text(f"SELECT COUNT(*) FROM conversations c {where}"),  # noqa: S608
            params,
        )
    ).scalar_one()

    params["limit"] = limit
    params["offset"] = offset
    rows = (
        await session.execute(
            text(f"{_CONV_SELECT} {where}{_CONV_ORDER}"),  # noqa: S608
            params,
        )
    ).fetchall()

    return ConversationsPage(
        items=[_to_summary(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: str,
    _: CurrentUser,
    session: SessionDep,
) -> ConversationDetail:
    row = (await session.execute(_SQL_CONV_BY_ID, {"conv_id": conv_id})).fetchone()
    if not row:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    msg_rows = (
        await session.execute(_SQL_LAST_MESSAGES, {"conv_id": conv_id})
    ).fetchall()
    messages = [_to_message(m) for m in msg_rows]

    return ConversationDetail(**_to_summary(row).model_dump(), messages=messages)


@router.patch("/{conv_id}", response_model=ConversationSummary)
async def patch_conversation(
    conv_id: str,
    body: PatchConversationRequest,
    _: CurrentUser,
    session: SessionDep,
) -> ConversationSummary:
    row = (await session.execute(_SQL_CONV_BY_ID, {"conv_id": conv_id})).fetchone()
    if not row:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if body.status is not None:
        await session.execute(
            _SQL_UPDATE_STATUS, {"status": body.status, "conv_id": conv_id}
        )
    if body.mark_read:
        await session.execute(_SQL_MARK_READ, {"conv_id": conv_id})

    await session.commit()

    row = (await session.execute(_SQL_CONV_BY_ID, {"conv_id": conv_id})).fetchone()
    return _to_summary(row)  # type: ignore[arg-type]


@router.get("/{conv_id}/messages", response_model=MessagesPage)
async def list_messages(
    conv_id: str,
    _: CurrentUser,
    session: SessionDep,
    before: Annotated[datetime | None, Query()] = None,
) -> MessagesPage:
    exists = (await session.execute(_SQL_CONV_EXISTS, {"conv_id": conv_id})).fetchone()
    if not exists:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if before is not None:
        rows = (
            await session.execute(
                _SQL_MESSAGES_WITH_CURSOR, {"conv_id": conv_id, "before": before}
            )
        ).fetchall()
    else:
        rows = (
            await session.execute(_SQL_MESSAGES_NO_CURSOR, {"conv_id": conv_id})
        ).fetchall()

    has_more = len(rows) == 51
    items = [_to_message(r) for r in rows[:50]]
    items.reverse()  # chronological order

    return MessagesPage(items=items, has_more=has_more)


@router.post("/{conv_id}/reply", response_model=MessageOut, status_code=201)
async def reply_to_conversation(
    conv_id: str,
    body: ReplyRequest,
    _: CurrentUser,
    session: SessionDep,
) -> MessageOut:
    """Send an outbound reply to an Airbnb conversation.

    Routing:
    - guest_contact ends with @reply.airbnb.com → SMTP (pre-booking inquiry)
    - guest_contact is numeric                  → Beds24 API (confirmed booking)
    """
    row = (
        await session.execute(_SQL_CONV_FOR_REPLY, {"conv_id": conv_id})
    ).fetchone()
    if not row:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Conversation not found")

    platform: str = row.platform
    guest_contact: str | None = row.guest_contact

    if platform not in ("airbnb", "booking", "direct"):
        raise HTTPException(
            http_status.HTTP_405_METHOD_NOT_ALLOWED,
            f"Reply not supported for platform '{platform}' via this endpoint",
        )

    # --- Send via appropriate path (raises on failure; no DB write on error) ---

    if guest_contact and guest_contact.endswith("@reply.airbnb.com"):
        # Pre-booking inquiry: SMTP → Airbnb reply gateway
        try:
            await send_smtp_reply(guest_contact, body.content)
        except Exception as exc:
            logger.exception("reply.smtp_failed conv_id=%s err=%s", conv_id, exc)
            raise HTTPException(
                http_status.HTTP_502_BAD_GATEWAY, "Failed to send email reply"
            ) from exc

    elif guest_contact and guest_contact.isdigit():
        # Confirmed booking: Beds24 API
        booking_id = int(guest_contact)
        s = get_settings()
        token_row = (await session.execute(_SQL_BEDS24_TOKEN)).fetchone()
        refresh_token = str(token_row[0]) if token_row else s.beds24_refresh_token
        try:
            async with httpx.AsyncClient(timeout=30) as http:
                client = Beds24Client(http)
                await client.authenticate(refresh_token)
                await client.post_message(booking_id, body.content)
        except Exception as exc:
            logger.exception("reply.beds24_failed conv_id=%s err=%s", conv_id, exc)
            raise HTTPException(
                http_status.HTTP_502_BAD_GATEWAY, "Failed to send Beds24 reply"
            ) from exc

    else:
        raise HTTPException(
            http_status.HTTP_405_METHOD_NOT_ALLOWED,
            "Cannot determine reply path for this conversation",
        )

    # --- Persist outbound message row ---
    sent_at = datetime.now(UTC)
    msg_hash = hashlib.sha256(
        f"reply:{conv_id}:{sent_at.isoformat()}".encode()
    ).hexdigest()
    is_smtp = "@reply" in (guest_contact or "")
    raw_headers = json.dumps({"reply_path": "smtp" if is_smtp else "beds24"})

    msg_row = (
        await session.execute(
            _SQL_INSERT_REPLY,
            {
                "conv_id": conv_id,
                "hash": msg_hash,
                "body": body.content,
                "sent_at": sent_at,
                "raw_headers": raw_headers,
            },
        )
    ).fetchone()
    await session.execute(
        _SQL_BUMP_LAST_MESSAGE, {"conv_id": conv_id, "sent_at": sent_at}
    )
    await session.commit()

    message_id = str(msg_row[0])  # type: ignore[index]

    # Fire-and-forget WS push
    from app.db.ingest import _try_publish  # noqa: PLC0415
    await _try_publish(conv_id, message_id, "outbound", body.content, sent_at)

    logger.info(
        "reply.sent conv_id=%s path=%s", conv_id, "smtp" if is_smtp else "beds24"
    )

    return MessageOut(
        id=message_id,
        direction="outbound",
        body=body.content,
        sent_at=sent_at,
        created_at=sent_at,
    )
