"""Airbnb email parser tests — all golden fixtures, no live I/O."""

from __future__ import annotations

import email
from pathlib import Path

from app.parsers.airbnb import (
    AirbnbParsedEmail,
    _extract_property_from_subject,
    is_airbnb_email,
    parse_airbnb_email,
)

FIXTURES = Path(__file__).parent / "fixtures" / "emails"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Golden fixture tests
# ---------------------------------------------------------------------------


def test_parse_airbnb_inquiry_golden() -> None:
    """Full parse of airbnb_inquiry.eml → all 5 fields correct."""
    raw = _load("airbnb_inquiry.eml")
    result = parse_airbnb_email(raw)

    assert isinstance(result, AirbnbParsedEmail)
    assert result.guest_name == "Shawnte'"
    assert result.reply_to == "4vy4m4jFAKETOKEN123abc@reply.airbnb.com"
    assert result.platform_conversation_id == "4vy4m4jFAKETOKEN123abc"
    assert result.property_name == "Apt3 - 3 bedrooms amazing sea view, terrace, Pool"
    # Message body must contain the guest's actual message, not boilerplate
    assert "29" in result.message_body
    assert "protection" not in result.message_body.lower()
    assert "Traduit" not in result.message_body


def test_parse_airbnb_message_golden() -> None:
    """Full parse of airbnb_message.eml → all 5 fields correct."""
    raw = _load("airbnb_message.eml")
    result = parse_airbnb_email(raw)

    assert isinstance(result, AirbnbParsedEmail)
    assert result.guest_name == "Jordan"
    assert result.reply_to == "9xk2p8qFAKETOKEN456def@reply.airbnb.com"
    assert result.platform_conversation_id == "9xk2p8qFAKETOKEN456def"
    assert result.property_name == "Studio Vue Mer - Résidence Caraïbes"
    assert "juillet" in result.message_body
    assert "protection" not in result.message_body.lower()


# ---------------------------------------------------------------------------
# Edge case: missing Reply-To
# ---------------------------------------------------------------------------


def test_parse_airbnb_missing_reply_to() -> None:
    """no_reply_to.eml → returns None (missing Reply-To header)."""
    raw = _load("airbnb_no_reply_to.eml")
    result = parse_airbnb_email(raw)
    assert result is None


# ---------------------------------------------------------------------------
# is_airbnb_email tests
# ---------------------------------------------------------------------------


def test_is_airbnb_email_reply_to() -> None:
    """Reply-To = TOKEN@reply.airbnb.com → True."""
    raw = (
        b"From: someone@example.com\r\n"
        b"Reply-To: sometoken@reply.airbnb.com\r\n"
        b"\r\n"
    )
    msg = email.message_from_bytes(raw)
    assert is_airbnb_email(msg) is True


def test_is_airbnb_email_from_domain() -> None:
    """From = automated@airbnb.com → True."""
    raw = b"From: Airbnb <automated@airbnb.com>\r\n\r\n"
    msg = email.message_from_bytes(raw)
    assert is_airbnb_email(msg) is True


def test_is_airbnb_email_booking() -> None:
    """From = noreply@booking.com → False."""
    raw = b"From: Booking.com <noreply@booking.com>\r\n\r\n"
    msg = email.message_from_bytes(raw)
    assert is_airbnb_email(msg) is False


# ---------------------------------------------------------------------------
# Subject extraction
# ---------------------------------------------------------------------------


def test_extract_property_from_subject() -> None:
    """Subject string → correct listing name without prefix or date range."""
    subject = (
        "Demande d\u2019information pour "
        "Apt3 - 3 bedrooms amazing sea view, terrace, Pool, 25-27 juin"
    )
    name = _extract_property_from_subject(subject)
    assert name == "Apt3 - 3 bedrooms amazing sea view, terrace, Pool"
