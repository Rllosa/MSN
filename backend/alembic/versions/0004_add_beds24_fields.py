"""Add beds24_property_id to properties and api_credentials table

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-08

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Stores rotating API tokens (Beds24 refresh token, future integrations)
    op.create_table(
        "api_credentials",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Maps Beds24 integer property ID to our UUID — used during message ingestion
    op.add_column(
        "properties",
        sa.Column("beds24_property_id", sa.Integer, nullable=True),
    )
    op.create_unique_constraint(
        "uq_properties_beds24_property_id",
        "properties",
        ["beds24_property_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_properties_beds24_property_id", "properties")
    op.drop_column("properties", "beds24_property_id")
    op.drop_table("api_credentials")
