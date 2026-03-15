"""Meta Cloud API async client — outbound WhatsApp messages only."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.facebook.com"


class WhatsAppAPIError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Meta API {status_code}: {body}")


class WhatsAppClient:
    """Sends outbound WhatsApp messages via the Meta Cloud API.

    Usage:
        async with httpx.AsyncClient(timeout=15) as http:
            client = WhatsAppClient(http, access_token, phone_number_id, api_version)
            wamid = await client.send_text(phone, body)
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        access_token: str,
        phone_number_id: str,
        api_version: str = "v21.0",
    ) -> None:
        self._http = http
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._api_version = api_version

    async def send_text(self, phone: str, body: str) -> str:
        """Send a text message. Returns the wamid on success.

        Raises WhatsAppAPIError on non-2xx response.
        """
        url = f"{_GRAPH_BASE}/{self._api_version}/{self._phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": body},
        }
        resp = await self._http.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        if resp.status_code >= 400:
            raise WhatsAppAPIError(resp.status_code, resp.text)
        return resp.json()["messages"][0]["id"]
