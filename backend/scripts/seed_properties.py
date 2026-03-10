"""Seed script — load 7 properties from backend/data/properties.yaml.

Usage (from backend/ directory):
    DATABASE_URL=postgresql+asyncpg://msn:msn@localhost:5433/msn \
        python scripts/seed_properties.py

Idempotent: upserts by slug. Safe to run multiple times.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


async def main() -> None:
    import asyncpg
    import yaml

    db_url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL or TEST_DATABASE_URL must be set", file=sys.stderr)
        sys.exit(1)

    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    data_file = Path(__file__).parent.parent / "data" / "properties.yaml"
    with data_file.open() as fh:
        data = yaml.safe_load(fh)

    properties = data["properties"]
    if len(properties) != 7:
        print(
            f"WARNING: expected 7 properties, found {len(properties)}",
            file=sys.stderr,
        )

    conn = await asyncpg.connect(dsn)
    try:
        for prop in properties:
            beds24_id = prop.get("beds24_property_id")
            row = await conn.fetchrow(
                """
                INSERT INTO properties (name, slug, beds24_property_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (slug)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    beds24_property_id = COALESCE(
                        EXCLUDED.beds24_property_id,
                        properties.beds24_property_id
                    )
                RETURNING id::text, name, slug, beds24_property_id,
                          (xmax = 0) AS inserted
                """,
                prop["name"],
                prop["slug"],
                beds24_id,
            )
            action = "inserted" if row["inserted"] else "updated"
            b24 = row["beds24_property_id"] or "not set"
            print(
                f"  {action}: {row['name']}"
                f" (slug={row['slug']}, id={row['id']}, beds24_id={b24})"
            )
    finally:
        await conn.close()

    print(f"Done — {len(properties)} properties seeded.")


if __name__ == "__main__":
    asyncio.run(main())
