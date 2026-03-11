"""Message ingestion — idempotent upsert pipeline for all platforms.

All SQL strings are pre-built at module scope (Rule 16.5).
Conversation upsert uses ON CONFLICT (platform, guest_contact) DO UPDATE.
Message insert uses ON CONFLICT (message_id_hash) DO NOTHING for deduplication.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.parsers.airbnb import AirbnbParsedEmail

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-built SQL (Rule 16.5 — never constructed inside a function)
# ---------------------------------------------------------------------------

_SQL_PROPERTY_BY_NAME = text(
    "SELECT id FROM properties WHERE LOWER(name) = LOWER(:name) LIMIT 1"
)

_SQL_PROPERTY_BY_BEDS24_ID = text(
    "SELECT id FROM properties WHERE beds24_property_id = :beds24_id LIMIT 1"
)

_SQL_UPSERT_CONVERSATION = text(
    """
    INSERT INTO conversations (platform, guest_name, guest_contact, property_id,
                               last_message_at, created_at, updated_at)
    VALUES (:platform, :guest_name, :guest_contact, :property_id,
            :sent_at, NOW(), NOW())
    ON CONFLICT (platform, guest_contact) DO UPDATE
        SET guest_name   = EXCLUDED.guest_name,
            property_id  = COALESCE(EXCLUDED.property_id, conversations.property_id),
            last_message_at = GREATEST(
                conversations.last_message_at, EXCLUDED.last_message_at
            ),
            updated_at   = NOW()
    RETURNING id
    """
)

_SQL_INSERT_MESSAGE = text(
    """
    INSERT INTO messages (conversation_id, message_id_hash, direction,
                          body, sent_at, raw_headers, created_at)
    VALUES (:conversation_id, :message_id_hash, :direction,
            :body, :sent_at, CAST(:raw_headers AS jsonb), NOW())
    ON CONFLICT (message_id_hash) DO NOTHING
    RETURNING id
    """
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def compute_hash(value: str) -> str:
    """Return SHA-256 hex digest of *value* — deterministic, collision-resistant."""
    return hashlib.sha256(value.encode()).hexdigest()


async def ingest_airbnb_email(
    parsed: AirbnbParsedEmail,
    session: AsyncSession,
) -> bool:
    """Persist a parsed Airbnb email to the DB.

    Returns True if a new message row was inserted, False if deduplicated.

    Steps:
      1. Property lookup by name (case-insensitive). NULL if not found.
      2. Conversation upsert via ON CONFLICT (platform, guest_contact).
      3. Message insert via ON CONFLICT (message_id_hash) DO NOTHING.
    """
    # 1. Property lookup
    row = await session.execute(_SQL_PROPERTY_BY_NAME, {"name": parsed.property_name})
    prop_row = row.first()
    property_id = str(prop_row[0]) if prop_row else None

    if not property_id:
        logger.warning(
            "ingest.airbnb.unknown_property property_name=%r conv_id=%s",
            parsed.property_name,
            parsed.platform_conversation_id,
        )

    # 2. Conversation upsert
    sent_at = parsed.sent_at or datetime.now(UTC)
    conv_result = await session.execute(
        _SQL_UPSERT_CONVERSATION,
        {
            "platform": "airbnb",
            "guest_name": parsed.guest_name,
            "guest_contact": parsed.reply_to,
            "property_id": property_id,
            "sent_at": sent_at,
        },
    )
    conversation_id = str(conv_result.scalar_one())

    # 3. Message insert
    message_hash = compute_hash(parsed.message_id_header)
    import json

    raw_headers = json.dumps(
        {
            "Message-ID": parsed.message_id_header,
            "Reply-To": parsed.reply_to,
        }
    )
    msg_result = await session.execute(
        _SQL_INSERT_MESSAGE,
        {
            "conversation_id": conversation_id,
            "message_id_hash": message_hash,
            "direction": "inbound",
            "body": parsed.message_body,
            "sent_at": sent_at,
            "raw_headers": raw_headers,
        },
    )
    inserted = msg_result.fetchone() is not None

    await session.commit()

    if inserted:
        logger.info(
            "ingest.airbnb.inserted conv_id=%s hash=%s",
            conversation_id,
            message_hash[:12],
        )
    else:
        logger.debug(
            "ingest.airbnb.duplicate hash=%s conv_id=%s",
            message_hash[:12],
            conversation_id,
        )

    return inserted


async def ingest_beds24_message(
    msg: dict,
    platform: str,
    booking: dict,
    session: AsyncSession,
) -> bool:
    """Persist a Beds24 guest message to the DB.

    Args:
        msg:      Single message dict from GET /bookings/messages.
        platform: 'airbnb' or 'booking' (derived from booking['channel']).
        booking:  Booking dict from GET /bookings for this message's bookingId.
        session:  Active async DB session.

    Returns True if a new message row was inserted, False if deduplicated.
    """
    booking_id = msg["bookingId"]
    beds24_property_id = msg.get("propertyId")

    # 1. Property lookup by beds24_property_id
    property_id: str | None = None
    if beds24_property_id is not None:
        row = await session.execute(
            _SQL_PROPERTY_BY_BEDS24_ID, {"beds24_id": beds24_property_id}
        )
        prop_row = row.first()
        property_id = str(prop_row[0]) if prop_row else None

    if not property_id:
        logger.warning(
            "ingest.beds24.unknown_property beds24_property_id=%s booking_id=%s",
            beds24_property_id,
            booking_id,
        )

    # 2. Conversation upsert — guest_contact = str(bookingId) (one conv per booking)
    guest_name = (
        f"{booking.get('firstName', '')} {booking.get('lastName', '')}".strip()
        or "Unknown"
    )
    sent_at_str: str = msg.get("time", "")
    try:
        sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        sent_at = datetime.now(UTC)

    conv_result = await session.execute(
        _SQL_UPSERT_CONVERSATION,
        {
            "platform": platform,
            "guest_name": guest_name,
            "guest_contact": str(booking_id),
            "property_id": property_id,
            "sent_at": sent_at,
        },
    )
    conversation_id = str(conv_result.scalar_one())

    # 3. Message insert — hash of Beds24 message ID (integer, globally unique)
    message_hash = compute_hash(str(msg["id"]))
    import json

    raw_headers = json.dumps(
        {
            "beds24_message_id": msg["id"],
            "bookingId": booking_id,
            "propertyId": beds24_property_id,
        }
    )
    msg_result = await session.execute(
        _SQL_INSERT_MESSAGE,
        {
            "conversation_id": conversation_id,
            "message_id_hash": message_hash,
            "direction": "inbound",
            "body": msg.get("message", ""),
            "sent_at": sent_at,
            "raw_headers": raw_headers,
        },
    )
    inserted = msg_result.fetchone() is not None

    await session.commit()

    if inserted:
        logger.info(
            "ingest.beds24.inserted platform=%s conv_id=%s hash=%s",
            platform,
            conversation_id,
            message_hash[:12],
        )
    else:
        logger.debug(
            "ingest.beds24.duplicate hash=%s conv_id=%s",
            message_hash[:12],
            conversation_id,
        )

    return inserted
