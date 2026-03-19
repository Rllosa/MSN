"""Add checkout_date to conversations for auto-archive of completed bookings.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("checkout_date", sa.Date(), nullable=True))
    op.execute(
        "CREATE INDEX ix_conversations_checkout_date"
        " ON conversations (checkout_date)"
        " WHERE checkout_date IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversations_checkout_date")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS checkout_date")
