"""Discover Beds24 property IDs and print a mapping to update properties.yaml.

Fetches all properties from the Beds24 API and prints their integer propId +
propName so you can fill in `beds24_property_id` in data/properties.yaml.

Usage (from backend/ directory):
    DATABASE_URL=postgresql+asyncpg://msn:msn@localhost:5433/msn \
        BEDS24_REFRESH_TOKEN=<token> \
        python scripts/discover_beds24_properties.py

The script also optionally updates properties in the DB directly if --update-db
is passed. Match is done on an exact (case-insensitive) propName → slug lookup
that you can adjust below.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def main(update_db: bool) -> None:
    import httpx

    refresh_token = os.environ.get("BEDS24_REFRESH_TOKEN")
    if not refresh_token:
        print("ERROR: BEDS24_REFRESH_TOKEN must be set", file=sys.stderr)
        sys.exit(1)

    async with httpx.AsyncClient(timeout=30) as http:
        # Authenticate
        auth_resp = await http.get(
            "https://beds24.com/api/v2/authentication/setup",
            headers={"token": refresh_token},
        )
        if auth_resp.status_code == 401:
            print("ERROR: refresh token rejected (401)", file=sys.stderr)
            sys.exit(1)
        auth_resp.raise_for_status()
        auth_data = auth_resp.json()
        if not auth_data.get("authenticated"):
            print(f"ERROR: auth failed: {auth_data}", file=sys.stderr)
            sys.exit(1)
        access_token = auth_data["token"]
        new_refresh = auth_data["refreshToken"]
        print(f"Authenticated. New refresh token (update .env!):\n  {new_refresh}\n")

        # Fetch properties
        props_resp = await http.get(
            "https://beds24.com/api/v2/properties",
            headers={"token": access_token},
        )
        props_resp.raise_for_status()
        props: list[dict] = props_resp.json() if props_resp.text.strip() else []

    if not props:
        print("No properties returned from Beds24.")
        return

    print("Beds24 properties:")
    print(f"  {'propId':<10} {'propName'}")
    print(f"  {'-'*10} {'-'*40}")
    for p in props:
        print(f"  {p.get('propId', '?'):<10} {p.get('propName', '?')}")

    print(
        "\nUpdate data/properties.yaml with the correct beds24_property_id for each"
        " property, then re-run scripts/seed_properties.py to persist to DB."
    )

    if update_db:
        db_url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
        if not db_url:
            print("ERROR: DATABASE_URL must be set for --update-db", file=sys.stderr)
            sys.exit(1)
        import asyncpg

        dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn)
        try:
            for p in props:
                prop_id = p.get("propId")
                prop_name = p.get("propName", "")
                row = await conn.fetchrow(
                    """
                    UPDATE properties
                    SET beds24_property_id = $1
                    WHERE LOWER(name) = LOWER($2)
                    RETURNING id::text, name, slug, beds24_property_id
                    """,
                    prop_id,
                    prop_name,
                )
                if row:
                    print(
                        f"  updated: {row['name']} → beds24_id={row['beds24_property_id']}"
                    )
                else:
                    print(
                        f"  no match in DB for propName={prop_name!r}"
                        " — update properties.yaml manually"
                    )
        finally:
            await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-db",
        action="store_true",
        help="Write beds24_property_id directly to the DB (name-based match)",
    )
    args = parser.parse_args()
    asyncio.run(main(update_db=args.update_db))
