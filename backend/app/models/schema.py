from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase

# NOTE: These models exist solely for Alembic autogenerate.
# All runtime database queries use raw parameterized SQL via asyncpg (see §3.2).
# Do NOT import these models in application code outside of migrations.

# Enum types — created by migration, not by SQLAlchemy (create_type=False)
platform_enum = sa.Enum(
    "airbnb",
    "booking",
    "whatsapp",
    name="platform_enum",
    create_type=False,
)
direction_enum = sa.Enum(
    "inbound",
    "outbound",
    name="direction_enum",
    create_type=False,
)


class Base(DeclarativeBase):
    pass


class Property(Base):
    __tablename__ = "properties"

    id = sa.Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    name = sa.Column(sa.String(255), nullable=False)
    slug = sa.Column(sa.String(100), nullable=False, unique=True)
    # Beds24 integer property ID — set via scripts/discover_beds24_properties.py
    beds24_property_id = sa.Column(sa.Integer, nullable=True, unique=True)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )


class ApiCredential(Base):
    """Key-value store for rotating API tokens (e.g. Beds24 refresh token)."""

    __tablename__ = "api_credentials"

    key = sa.Column(sa.Text, primary_key=True)
    value = sa.Column(sa.Text, nullable=False)
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )


class User(Base):
    __tablename__ = "users"

    id = sa.Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    email = sa.Column(sa.String(255), nullable=False, unique=True)
    password_hash = sa.Column(sa.String(255), nullable=False)
    is_active = sa.Column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("TRUE"),
    )
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Enables ON CONFLICT (platform, guest_contact) DO UPDATE — idempotent upsert
        sa.UniqueConstraint(
            "platform", "guest_contact",
            name="uq_conversations_platform_guest_contact",
        ),
    )

    id = sa.Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    platform = sa.Column(platform_enum, nullable=False)
    guest_name = sa.Column(sa.String(255), nullable=False)
    # email for Airbnb/Booking, phone number for WhatsApp
    guest_contact = sa.Column(sa.String(500))
    property_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("properties.id", ondelete="SET NULL"),
    )
    # Booking.com extranet URL for reply redirect (v1 reply strategy)
    external_url = sa.Column(sa.Text)
    # Denormalized for fast inbox sort — updated on every message insert
    last_message_at = sa.Column(sa.DateTime(timezone=True))
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )


class Message(Base):
    __tablename__ = "messages"

    id = sa.Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    conversation_id = sa.Column(
        UUID(as_uuid=True),
        sa.ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SHA-256 hex of the email Message-ID header; used for deduplication (SOLO-111)
    message_id_hash = sa.Column(sa.String(64), nullable=False, unique=True)
    direction = sa.Column(direction_enum, nullable=False)
    body = sa.Column(sa.Text, nullable=False)
    sent_at = sa.Column(sa.DateTime(timezone=True), nullable=False)
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    # Filtered JSONB: only Message-ID, Reply-To, Subject, From, Date stored
    raw_headers = sa.Column(JSONB)


class Template(Base):
    __tablename__ = "templates"

    id = sa.Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    name = sa.Column(sa.String(255), nullable=False)
    content = sa.Column(sa.Text, nullable=False)
    # Empty array = applies to all platforms; otherwise ['airbnb'], ['whatsapp'], etc.
    platform_scope = sa.Column(
        ARRAY(sa.String(20)),
        nullable=False,
        server_default=sa.text("ARRAY[]::varchar(20)[]"),
    )
    # TODO(SOLO-124): trigger_keywords drive auto-reply dispatch
    trigger_keywords = sa.Column(
        ARRAY(sa.String(100)),
        nullable=False,
        server_default=sa.text("ARRAY[]::varchar(100)[]"),
    )
    created_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
    updated_at = sa.Column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("NOW()"),
    )
