from __future__ import annotations

import email
import email.header
import email.utils
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from email.message import Message

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns — Rule 16.5: never compiled inside a function
# ---------------------------------------------------------------------------

# Reply-To: TOKEN@reply.airbnb.com  (token may contain letters, digits, hyphens)
_RE_REPLY_TO = re.compile(r"^([^@\s]+)@reply\.airbnb\.com$", re.IGNORECASE)

# Airbnb sender domain check
_RE_AIRBNB_FROM = re.compile(r"@(?:[a-z0-9.-]+\.)?airbnb\.com", re.IGNORECASE)

# Optional "Objet : " or "Object : " prefix (French/English "Subject:") that
# Airbnb prepends in some locales.
_RE_SUBJECT_OBJET = re.compile(r"^Objet\s*\xa0?:\s*", re.IGNORECASE)

# Only ingest pre-booking inquiry emails — skip booking confirmations, messages, etc.
_RE_SUBJECT_INQUIRY = re.compile(
    r"^Demande\s+d['\u2019]information\s+pour\b",
    re.IGNORECASE,
)

# Subject prefixes where the remainder IS the property name (+ optional date range)
_RE_SUBJECT_PREFIX = re.compile(
    r"^(?:"
    r"Demande\s+d['\u2019]information\s+pour"
    r"|Demande\s+pour"
    r"|Nouvelle\s+demande\s+de\s+r[eé]servation\s+pour"
    r"|R[eé]servation\s+(?:de\s+.+\s+)?pour"
    r"|Inquiry\s+about"
    r"|Reservation\s+(?:request\s+)?for"
    r")\s+",
    re.IGNORECASE,
)

# Subject prefixes where the remainder is the guest name, NOT a property name
_RE_SUBJECT_NO_PROPERTY = re.compile(
    r"^(?:Message\s+de|Message\s+from)\s+",
    re.IGNORECASE,
)

# Trailing date range: ", 25–27 juin" or ", Jun 25–27" or ", 25-27 juin"
_RE_TRAILING_DATE = re.compile(
    r",\s*\d{1,2}[–—\-]\d{1,2}\s+\w+\s*$" r"|\s*,\s*\w+\s+\d{1,2}[–—\-]\d{1,2}\s*$",
)

# Role labels that Airbnb injects above the message — strip from body
_RE_ROLE_LABEL = re.compile(
    r"^(?:Responsable\s+de\s+la\s+r[eé]servation|Co-h[oô]te|H[oô]te|Guest|Host)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Detect host (outbound) role label — "Co-hôte" or standalone "Hôte"
_RE_ROLE_HOST = re.compile(r"^(?:Co-h[oô]te|H[oô]te)$", re.IGNORECASE)

# Boilerplate blocks to strip from message body (French + English)
_BOILERPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"Pour votre protection.*?Airbnb\s*\.?\s*",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"For your (?:protection|safety).*?Airbnb\s*\.?\s*",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"Traduit automatiquement.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"Automatically translated.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"Vous pouvez [eé]galement r[eé]pondre.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"You can also reply.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"Appartement en r[eé]sidence.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"T[eé]l[eé]chargez l.application.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"Airbnb Ireland.*$", re.IGNORECASE | re.DOTALL),
    re.compile(r"Modifiez vos pr[eé]f[eé]rences.*$", re.IGNORECASE | re.DOTALL),
)

# Anchor for property name in body: "Hôte :" or "Host:"
_RE_HOST_ANCHOR = re.compile(r"H[oô]te\s*:|Host\s*:", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AirbnbParsedEmail:
    guest_name: str
    message_body: str
    direction: str  # "inbound" (guest) or "outbound" (host reply echoed by Airbnb)
    reply_to: str  # full address: TOKEN@reply.airbnb.com
    platform_conversation_id: str  # token portion before @
    property_name: str  # raw listing name; caller does case-insensitive DB lookup
    # Used by ingest layer for deduplication hash and DB timestamp
    message_id_header: str  # raw Message-ID header value (or fallback synthetic ID)
    sent_at: datetime | None  # parsed from Date: header; None if absent/unparseable


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_airbnb_email(msg: Message) -> bool:
    """Return True if the email originates from Airbnb."""
    reply_to = msg.get("Reply-To", "")
    from_header = msg.get("From", "")
    return bool(_RE_REPLY_TO.search(reply_to) or _RE_AIRBNB_FROM.search(from_header))


def parse_airbnb_email(raw_bytes: bytes) -> AirbnbParsedEmail | None:
    """
    Parse a raw Airbnb notification email.

    Returns None (with a warning log) if required fields cannot be extracted.
    Never raises — graceful degradation per Rule 1.3.
    """
    msg = email.message_from_bytes(raw_bytes)
    message_id_header = (msg.get("Message-ID") or "").strip()
    message_id = message_id_header or "<unknown>"
    sent_at = _parse_date(msg.get("Date", ""))

    # 0. Only ingest pre-booking inquiry emails ("Demande d'information pour …")
    raw_subject = _decode_header(msg.get("Subject", ""))
    clean_subject = _RE_SUBJECT_OBJET.sub("", raw_subject).strip()
    if not _RE_SUBJECT_INQUIRY.match(clean_subject):
        logger.debug(
            "airbnb.skipped_non_inquiry message_id=%s subject=%r",
            message_id,
            clean_subject[:60],
        )
        return None

    # 1. Reply-To → reply address + platform conversation ID
    reply_to_header = msg.get("Reply-To", "").strip()
    m = _RE_REPLY_TO.match(reply_to_header)
    if not m:
        # Reservation-request emails ("Demande pour …") have no Reply-To token —
        # Airbnb expects pre-approval via their UI, not email reply.
        # TODO(SOLO-118): store these as read-only conversations with a
        #   "Répondre sur Airbnb" link instead of an in-app reply box.
        logger.warning(
            "airbnb.parse_failed reason=missing_reply_to message_id=%s",
            message_id,
        )
        return None
    reply_to = reply_to_header
    platform_conversation_id = m.group(1)

    # 2. Property name — primary: subject; fallback: HTML body
    subject = _decode_header(msg.get("Subject", ""))
    property_name = _extract_property_from_subject(subject)

    # 3. HTML body → direction, guest name, message text
    html = _get_html_body(msg)
    if html:
        soup = BeautifulSoup(html, "html.parser")
        direction = _extract_direction(soup)
        guest_name = _extract_guest_name(soup) or "Unknown"
        message_body = _extract_message_body(soup)
        if not property_name:
            property_name = _extract_property_from_body(soup) or ""
    else:
        plain = _get_plain_body(msg) or ""
        direction = "inbound"
        guest_name = "Unknown"
        message_body = plain.strip()

    if not message_body:
        logger.warning(
            "airbnb.parse_failed reason=empty_body message_id=%s",
            message_id,
        )
        return None

    logger.debug(
        "airbnb.parsed guest=%s property=%s conv_id=%s",
        guest_name,
        property_name,
        platform_conversation_id,
    )
    return AirbnbParsedEmail(
        guest_name=guest_name,
        message_body=message_body,
        direction=direction,
        reply_to=reply_to,
        platform_conversation_id=platform_conversation_id,
        property_name=property_name,
        message_id_header=message_id_header or reply_to,
        sent_at=sent_at,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _decode_header(raw: str) -> str:
    """Decode a MIME-encoded email header (e.g. =?UTF-8?B?...?=) to plain text."""
    parts = email.header.decode_header(raw)
    decoded = str(email.header.make_header(parts))
    return decoded


def _extract_property_from_subject(subject: str) -> str:
    """Strip Airbnb subject prefix and trailing date range; return listing name.

    Returns empty string for subject patterns where the remainder is the
    guest name rather than a property name (e.g. "Message de Jordan").
    """
    # Strip leading "Objet : " / "Objet\xa0: " (French "Subject:") if present
    subject = _RE_SUBJECT_OBJET.sub("", subject)
    if _RE_SUBJECT_NO_PROPERTY.match(subject):
        return ""
    name = _RE_SUBJECT_PREFIX.sub("", subject).strip()
    name = _RE_TRAILING_DATE.sub("", name).strip()
    return name


def _get_html_body(msg: Message) -> str | None:
    """Return the first text/html payload found in the MIME tree."""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return None


def _get_plain_body(msg: Message) -> str | None:
    """Return the first text/plain payload found in the MIME tree."""
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return None


def _extract_guest_name(soup: BeautifulSoup) -> str | None:
    """
    Airbnb inquiry emails render the guest name as the first <h2> tag,
    followed by their role ("Responsable de la réservation").
    """
    for tag in soup.find_all("h2"):
        text = tag.get_text(strip=True)
        if text and len(text) < 80 and "\n" not in text:
            return text
    return None


def _extract_direction(soup: BeautifulSoup) -> str:
    """Return 'outbound' if the first role label is Co-hôte/Hôte (host), else 'inbound'.

    Checks only the first role-label paragraph — threads include quoted history
    with the other party's role label, which must be ignored.
    """
    for tag in soup.find_all("p"):
        text = tag.get_text(strip=True)
        if _RE_ROLE_LABEL.match(text):
            return "outbound" if _RE_ROLE_HOST.match(text) else "inbound"
    return "inbound"


def _extract_message_body(soup: BeautifulSoup) -> str:
    """
    Collect all <p> text, strip role labels ("Responsable de la réservation",
    "Co-hôte") and Airbnb boilerplate. Returns clean plain text.
    """
    paragraphs = [p.get_text(separator=" ", strip=True) for p in soup.find_all("p")]
    # Drop role labels and bare punctuation-only paragraphs
    filtered = [
        p
        for p in paragraphs
        if p and not _RE_ROLE_LABEL.match(p) and not re.fullmatch(r"[.\-–—\s]+", p)
    ]
    raw = "\n\n".join(filtered)

    for pattern in _BOILERPLATE_PATTERNS:
        raw = pattern.sub("", raw)

    # Strip any stray leading punctuation left by boilerplate removal
    raw = re.sub(r"^[.\-–—\s]+", "", raw)
    return raw.strip()


def _parse_date(date_str: str) -> datetime | None:
    """Parse RFC 2822 Date header into a timezone-aware datetime, or None."""
    if not date_str:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed
    except Exception:
        return None


def _extract_property_from_body(soup: BeautifulSoup) -> str | None:
    """
    Fallback property extraction: find the bold listing name that precedes
    the 'Hôte :' / 'Host:' host line in the property summary block.
    """
    host_node = soup.find(string=_RE_HOST_ANCHOR)
    if not host_node:
        return None
    parent = host_node.find_parent()
    if not parent:
        return None
    prev = parent.find_previous(["strong", "b", "h2", "h3"])
    if prev:
        return prev.get_text(strip=True)
    return None
