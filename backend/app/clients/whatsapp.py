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
            media_id = await client.upload_media(file_bytes, mime_type, filename)
            wamid = await client.send_image(phone, media_id, caption)
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

    @property
    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}

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
        resp = await self._http.post(url, json=payload, headers=self._auth_header)
        if resp.status_code >= 400:
            raise WhatsAppAPIError(resp.status_code, resp.text)
        return resp.json()["messages"][0]["id"]

    async def upload_media(
        self, file_bytes: bytes, mime_type: str, filename: str
    ) -> str:
        """Upload media to Meta. Returns the media_id.

        Must be called before send_image. The media_id is ephemeral — use it
        immediately in the same request cycle.
        Raises WhatsAppAPIError on non-2xx response.
        """
        url = f"{_GRAPH_BASE}/{self._api_version}/{self._phone_number_id}/media"
        resp = await self._http.post(
            url,
            headers=self._auth_header,
            files={"file": (filename, file_bytes, mime_type)},
            data={"messaging_product": "whatsapp"},
        )
        if resp.status_code >= 400:
            raise WhatsAppAPIError(resp.status_code, resp.text)
        return resp.json()["id"]

    async def send_image(self, phone: str, media_id: str, caption: str = "") -> str:
        """Send an image message using a previously uploaded media_id.

        caption is optional. Returns the wamid on success.
        Raises WhatsAppAPIError on non-2xx response.
        """
        url = f"{_GRAPH_BASE}/{self._api_version}/{self._phone_number_id}/messages"
        image_payload: dict[str, str] = {"id": media_id}
        if caption:
            image_payload["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "image",
            "image": image_payload,
        }
        resp = await self._http.post(url, json=payload, headers=self._auth_header)
        if resp.status_code >= 400:
            raise WhatsAppAPIError(resp.status_code, resp.text)
        return resp.json()["messages"][0]["id"]
