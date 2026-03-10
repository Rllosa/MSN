"""Add UNIQUE(platform, guest_contact) to conversations for idempotent upsert

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-10

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enables ON CONFLICT (platform, guest_contact) DO UPDATE for conversation
    # threading — one row per (platform, contact) regardless of poll frequency.
    op.create_unique_constraint(
        "uq_conversations_platform_guest_contact",
        "conversations",
        ["platform", "guest_contact"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_conversations_platform_guest_contact",
        "conversations",
    )
