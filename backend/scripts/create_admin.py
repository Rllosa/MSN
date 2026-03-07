"""Bootstrap script — create or promote an admin user.

Usage:
    python scripts/create_admin.py --email admin@example.com --password changeme

Idempotent: if the email already exists, is_admin and is_active are set to TRUE
and the password is updated.

Requires DATABASE_URL env var (or TEST_DATABASE_URL for local dev).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


async def main(email: str, password: str) -> None:
    # Import here so the script is runnable from the backend/ directory
    # without modifying sys.path (alembic.ini is the CWD anchor).
    import asyncpg

    from app.auth.hashing import hash_password

    db_url = os.environ.get("DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL or TEST_DATABASE_URL must be set", file=sys.stderr)
        sys.exit(1)

    # asyncpg uses the plain postgresql:// scheme
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")
    pw_hash = hash_password(password)

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, password_hash, is_active, is_admin)
            VALUES ($1, $2, TRUE, TRUE)
            ON CONFLICT (email)
            DO UPDATE SET is_admin = TRUE, is_active = TRUE, password_hash = $2
            RETURNING id::text, email, is_admin
            """,
            email,
            pw_hash,
        )
    finally:
        await conn.close()

    print(
        f"Admin ready: id={row['id']} email={row['email']} is_admin={row['is_admin']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create or promote an admin user")
    parser.add_argument("--email", required=True, help="Admin user email")
    parser.add_argument("--password", required=True, help="Admin user password")
    args = parser.parse_args()
    asyncio.run(main(args.email, args.password))
