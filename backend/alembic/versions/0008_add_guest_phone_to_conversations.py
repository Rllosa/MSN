"""Add guest_phone to conversations for cross-platform linking.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-15
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS guest_phone TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_guest_phone"
        " ON conversations (guest_phone)"
        " WHERE guest_phone IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_conversations_guest_phone")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS guest_phone")
