"""Meta Cloud API webhook endpoints.

GET  /webhooks/whatsapp — hub verification challenge (no auth, Meta sends it)
POST /webhooks/whatsapp — inbound message delivery (HMAC-SHA256 validated)

Security: Meta signs every POST with X-Hub-Signature-256: sha256=<hex>.
We validate with hmac.compare_digest (constant-time) before processing.
A 200 is returned immediately; DB writes run in a BackgroundTask so Meta
never retries due to slow DB (Rule 1.2 / 1.3).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Request, Response
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.db.session import worker_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_UNSUPPORTED_BODY = "[Unsupported message type]"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/whatsapp")
async def whatsapp_verify(request: Request) -> Response:
    """Respond to Meta's webhook verification challenge."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token == get_settings().whatsapp_verify_token:
        return PlainTextResponse(challenge, status_code=200)

    logger.warning("whatsapp.webhook.verify_failed mode=%s", mode)
    return Response(status_code=403)


@router.post("/whatsapp", status_code=200)
async def whatsapp_inbound(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive an inbound WhatsApp message from Meta Cloud API.

    Validates HMAC-SHA256 signature, returns 200 immediately, and processes
    the payload in a background task so Meta never times out waiting for us.
    """
    raw_body = await request.body()

    # Constant-time HMAC validation — reject unsigned/tampered requests
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        get_settings().whatsapp_app_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(sig_header, expected):
        logger.warning("whatsapp.webhook.invalid_signature")
        return Response(status_code=401)

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("whatsapp.webhook.invalid_json")
        return {}

    background_tasks.add_task(_process_whatsapp_payload, payload)
    return {}


# ---------------------------------------------------------------------------
# Background processor
# ---------------------------------------------------------------------------


async def _process_whatsapp_payload(payload: dict) -> None:
    """Extract messages from a Meta webhook payload and ingest each one."""
    from app.db.ingest import ingest_whatsapp_message  # avoid circular import

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages")

            if not messages:
                # Delivery/read receipt — no action needed
                logger.debug("whatsapp.webhook.status_update_skipped")
                continue

            contact_map: dict[str, str] = {
                c["wa_id"]: c.get("profile", {}).get("name", "Unknown")
                for c in value.get("contacts", [])
            }

            for msg in messages:
                wa_id: str = msg.get("from", "")
                wamid: str = msg.get("id", "")
                ts_str: str = msg.get("timestamp", "")
                msg_type: str = msg.get("type", "")

                body = (
                    msg.get("text", {}).get("body", "")
                    if msg_type == "text"
                    else _UNSUPPORTED_BODY
                )
                guest_name = contact_map.get(wa_id, "Unknown")

                try:
                    sent_at = datetime.fromtimestamp(int(ts_str), tz=UTC)
                except (ValueError, TypeError):
                    sent_at = datetime.now(UTC)

                try:
                    async with worker_session() as session:
                        await ingest_whatsapp_message(
                            wamid=wamid,
                            phone=wa_id,
                            guest_name=guest_name,
                            body=body,
                            sent_at=sent_at,
                            session=session,
                        )
                except Exception:
                    logger.exception(
                        "whatsapp.webhook.ingest_failed wamid=%s", wamid
                    )
