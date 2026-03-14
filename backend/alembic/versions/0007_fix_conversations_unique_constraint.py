"""Replace (platform, guest_contact) unique constraint with partial unique index on guest_contact

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-14

The old constraint allowed the same guest_contact to have separate rows per
platform (e.g. one 'airbnb' and one 'booking' row for the same booking ID),
causing duplicate conversations when platform detection flipped between polls.

The new partial unique index enforces at most one conversation per guest_contact
(where non-NULL), with the upsert handling platform upgrades atomically.

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the old (platform, guest_contact) unique constraint that allowed
    # duplicates when the same contact appeared under multiple platforms.
    op.drop_constraint(
        "uq_conversations_platform_guest_contact",
        "conversations",
        type_="unique",
    )

    # Create a partial unique index — NULL guest_contact rows are excluded so
    # multiple conversations without a contact are allowed (e.g. WhatsApp stubs).
    op.execute(
        "CREATE UNIQUE INDEX uq_conversations_guest_contact"
        " ON conversations (guest_contact)"
        " WHERE guest_contact IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_conversations_guest_contact")
    op.create_unique_constraint(
        "uq_conversations_platform_guest_contact",
        "conversations",
        ["platform", "guest_contact"],
    )
