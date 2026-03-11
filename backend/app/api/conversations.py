"""Conversations and messages REST API.

GET   /conversations              — paginated inbox, filterable
GET   /conversations/{id}         — conversation detail + last 50 messages
PATCH /conversations/{id}         — archive/unarchive or mark read
GET   /conversations/{id}/messages — cursor-based message history
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import text

from app.auth.dependencies import CurrentUser
from app.db.session import SessionDep

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
    " ORDER BY (c.unread_count > 0) DESC,"
    " c.last_message_at DESC NULLS LAST"
    " LIMIT :limit OFFSET :offset"
)

_SQL_CONV_BY_ID = text(
    f"{_CONV_SELECT} WHERE c.id = :conv_id"  # noqa: S608
)

_SQL_LAST_MESSAGES = text("""
    SELECT id::text, direction::text, body, sent_at, created_at
    FROM messages
    WHERE conversation_id = :conv_id
    ORDER BY sent_at DESC
    LIMIT 50
""")

_SQL_MESSAGES_WITH_CURSOR = text("""
    SELECT id::text, direction::text, body, sent_at, created_at
    FROM messages
    WHERE conversation_id = :conv_id
      AND sent_at < :before
    ORDER BY sent_at DESC
    LIMIT 51
""")

_SQL_MESSAGES_NO_CURSOR = text("""
    SELECT id::text, direction::text, body, sent_at, created_at
    FROM messages
    WHERE conversation_id = :conv_id
    ORDER BY sent_at DESC
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


# ---------------------------------------------------------------------------
# Dynamic WHERE builder — WHERE content varies per request, values parameterized
# ---------------------------------------------------------------------------


def _build_where(
    platform: str | None,
    property_ids: list[str] | None,
    conv_status: str | None,
    search: str | None,
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

    if platform is not None:
        clauses.append("c.platform::text = :platform")
        params["platform"] = platform

    if property_ids:
        # Named placeholders for each ID avoids array binding complexity
        ph = ", ".join(f":prop{i}" for i in range(len(property_ids)))
        clauses.append(f"c.property_id::text IN ({ph})")  # noqa: S608
        for i, pid in enumerate(property_ids):
            params[f"prop{i}"] = pid

    if search is not None:
        clauses.append("(c.guest_name ILIKE :search OR c.guest_contact ILIKE :search)")
        params["search"] = f"%{search}%"

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
    platform: Annotated[
        Literal["airbnb", "booking", "whatsapp", "direct"] | None, Query()
    ] = None,
    property_id: Annotated[str | None, Query()] = None,
    conv_status: Annotated[
        Literal["active", "archived"] | None, Query(alias="status")
    ] = None,
    search: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationsPage:
    property_ids = (
        [p.strip() for p in property_id.split(",") if p.strip()]
        if property_id
        else None
    )
    where, params = _build_where(platform, property_ids, conv_status, search)

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

    # Last 50 messages fetched DESC, reversed to chronological for the response
    msg_rows = (
        await session.execute(_SQL_LAST_MESSAGES, {"conv_id": conv_id})
    ).fetchall()
    messages = [_to_message(m) for m in reversed(msg_rows)]

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
