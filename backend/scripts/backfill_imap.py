"""
One-off script: fetch all emails from the last N days via IMAP and ingest
any Airbnb inquiry emails into the DB (idempotent — deduplication via message hash).

Usage (from backend/):
    python scripts/backfill_imap.py [--days 14]
"""
from __future__ import annotations

import argparse
import asyncio
import email
import imaplib
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.config import get_settings
from app.db.ingest import ingest_airbnb_email
from app.db.session import init_engine, worker_session
from app.parsers.airbnb import is_airbnb_email, parse_airbnb_email

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def backfill_async(days: int) -> None:
    init_engine()
    s = get_settings()
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")

    logger.info("Connecting to %s:%d as %s", s.imap_host, s.imap_port, s.imap_user)
    mail = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
    mail.login(s.imap_user, s.imap_password)
    mail.select("INBOX", readonly=True)

    _, data = mail.search(None, f"SINCE {since_date}")
    uids = data[0].split() if data[0] else []
    logger.info("Found %d emails since %s — scanning for Airbnb inquiries…", len(uids), since_date)

    found = ingested = skipped = errors = 0

    for i, uid in enumerate(uids, 1):
        try:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            if not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, bytes):
                continue

            msg = email.message_from_bytes(raw)
            if not is_airbnb_email(msg):
                continue

            found += 1
            parsed = parse_airbnb_email(raw)
            if not parsed:
                errors += 1
                continue

            logger.info(
                "  guest=%-20s property=%-35r conv_id=%s",
                parsed.guest_name,
                parsed.property_name,
                parsed.platform_conversation_id,
            )

            async with worker_session() as session:
                inserted = await ingest_airbnb_email(parsed, session)
                if inserted:
                    ingested += 1
                else:
                    skipped += 1

            # Brief pause every 50 fetches to respect OVH rate limits
            if i % 50 == 0:
                time.sleep(1)

        except Exception as exc:
            logger.warning("  uid=%s error=%s", uid, exc)
            errors += 1

    mail.logout()
    logger.info(
        "Done. airbnb_inquiries=%d  ingested=%d  deduplicated=%d  errors=%d",
        found,
        ingested,
        skipped,
        errors,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    asyncio.run(backfill_async(args.days))


if __name__ == "__main__":
    main()
