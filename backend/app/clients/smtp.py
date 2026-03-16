"""Async SMTP helper for outbound replies via OVH mail server.

Used by the Airbnb pre-booking inquiry reply path (SOLO-118).
Credentials and host are read from config — never hardcoded (Rule 1.1).
"""

from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_smtp_reply(
    to_address: str,
    body: str,
    attachment: bytes | None = None,
    attachment_name: str | None = None,
    attachment_mime_type: str | None = None,
) -> None:
    """Send a reply to *to_address* via OVH SMTP.

    Optionally includes a binary attachment (image).
    Raises on SMTP error — caller is responsible for 502 response.
    """
    s = get_settings()

    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to_address
    msg["Subject"] = "Re: Your inquiry"
    msg.set_content(body or "")

    if attachment is not None and attachment_name and attachment_mime_type:
        main_type, sub_type = attachment_mime_type.split("/", 1)
        msg.add_attachment(
            attachment,
            maintype=main_type,
            subtype=sub_type,
            filename=attachment_name,
        )

    await aiosmtplib.send(
        msg,
        hostname=s.smtp_host,
        port=s.smtp_port,
        username=s.smtp_user,
        password=s.smtp_password,
        start_tls=True,
    )
    logger.info("smtp.sent to=%s attachment=%s", to_address, attachment_name or "none")
