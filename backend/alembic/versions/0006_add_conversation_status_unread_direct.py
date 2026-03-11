"""Add status, unread_count to conversations; add direct to platform_enum

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extend platform_enum with 'direct' for Beds24 bookings whose channel is
    # not Airbnb or Booking.com (e.g. manually entered direct bookings).
    # IF NOT EXISTS requires PostgreSQL 9.3+; ADD VALUE is safe in PG 12+ transactions.
    op.execute("ALTER TYPE platform_enum ADD VALUE IF NOT EXISTS 'direct'")

    # Conversation status: 'active' (default inbox) or 'archived'
    op.add_column(
        "conversations",
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),
    )

    # Denormalized unread counter — incremented on inbound message ingest,
    # reset to 0 when the user opens the conversation.
    op.add_column(
        "conversations",
        sa.Column(
            "unread_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Index for status filter (default inbox query always filters status='active')
    op.create_index("idx_conversations_status", "conversations", ["status"])


def downgrade() -> None:
    op.drop_index("idx_conversations_status", table_name="conversations")
    op.drop_column("conversations", "unread_count")
    op.drop_column("conversations", "status")
    # PostgreSQL does not support removing enum values — requires type recreation.
    # Acceptable: 'direct' is a no-op when unused.
