"""Initial schema — properties, users, conversations, messages, templates

Revision ID: 0001
Revises: None
Create Date: 2026-03-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Enum types ---
    # DO blocks are used because PostgreSQL has no CREATE TYPE IF NOT EXISTS
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE platform_enum AS ENUM ('airbnb', 'booking', 'whatsapp');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE direction_enum AS ENUM ('inbound', 'outbound');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # --- properties ---
    op.create_table(
        "properties",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("slug", name="uq_properties_slug"),
    )

    # --- users ---
    op.create_table(
        "users",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    # --- conversations ---
    op.create_table(
        "conversations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "platform",
            sa.Enum(
                "airbnb", "booking", "whatsapp", name="platform_enum", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("guest_name", sa.String(255), nullable=False),
        # email address for Airbnb/Booking, phone number for WhatsApp
        sa.Column("guest_contact", sa.String(500)),
        sa.Column(
            "property_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "properties.id",
                ondelete="SET NULL",
                name="fk_conversations_property_id",
            ),
        ),
        # Booking.com extranet URL for reply redirect (v1 reply strategy)
        sa.Column("external_url", sa.Text),
        # Denormalized for fast inbox sort — updated on every message insert (SOLO-108)
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    # Composite indexes for inbox query: filter by property or platform, sort by recency
    op.create_index(
        "ix_conversations_property_last_message",
        "conversations",
        ["property_id", sa.text("last_message_at DESC")],
    )
    op.create_index(
        "ix_conversations_platform_last_message",
        "conversations",
        ["platform", sa.text("last_message_at DESC")],
    )

    # --- messages ---
    op.create_table(
        "messages",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "conversations.id",
                ondelete="CASCADE",
                name="fk_messages_conversation_id",
            ),
            nullable=False,
        ),
        # SHA-256 hex of the email Message-ID header — used for deduplication (SOLO-111)
        sa.Column("message_id_hash", sa.String(64), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("inbound", "outbound", name="direction_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # Filtered subset: Message-ID, Reply-To, Subject, From, Date
        sa.Column("raw_headers", JSONB),
        sa.UniqueConstraint("message_id_hash", name="uq_messages_message_id_hash"),
    )
    # Composite index for paginated message thread queries
    op.create_index(
        "ix_messages_conversation_sent_at",
        "messages",
        ["conversation_id", sa.text("sent_at DESC")],
    )

    # --- templates ---
    op.create_table(
        "templates",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        # Empty array = all platforms; ['airbnb'] = Airbnb only, etc.
        sa.Column(
            "platform_scope",
            ARRAY(sa.String(20)),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar(20)[]"),
        ),
        # TODO(SOLO-124): trigger_keywords drive auto-reply dispatch
        sa.Column(
            "trigger_keywords",
            ARRAY(sa.String(100)),
            nullable=False,
            server_default=sa.text("ARRAY[]::varchar(100)[]"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("templates")
    op.drop_index("ix_messages_conversation_sent_at", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_platform_last_message", table_name="conversations")
    op.drop_index("ix_conversations_property_last_message", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("users")
    op.drop_table("properties")
    # Drop enum types after all tables that reference them are gone
    op.execute("DROP TYPE IF EXISTS direction_enum")
    op.execute("DROP TYPE IF EXISTS platform_enum")
