"""Beds24 v2 API async client.

Authentication flow (corrected from initial SOLO-110 implementation):
  - GET /authentication/token with header `refreshToken: <token>` → access token
    (86 400 s expiry). Beds24 only rotates the refresh token occasionally; when it
    does, `refreshToken` appears in the response. When absent, the existing
    refresh token remains valid.
  - All other calls use header `token: <access_token>`.

Endpoints used:
  - GET /bookings/messages  — paginated guest/host message feed
  - GET /bookings           — booking detail (guest info, channel attribution)
  - GET /properties         — property list (for ID mapping)

Reference: https://beds24.com/api/v2
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BEDS24_BASE = "https://beds24.com/api/v2"

# Beds24 channel values → our platform enum values
BEDS24_CHANNEL_MAP: dict[str, str] = {
    "airbnb": "airbnb",
    "booking": "booking",
}


class Beds24AuthError(Exception):
    """Raised when Beds24 rejects the refresh token."""


class Beds24Client:
    """Async Beds24 v2 API client.

    Usage:
        async with httpx.AsyncClient(timeout=30) as http:
            client = Beds24Client(http)
            new_refresh = await client.authenticate(refresh_token)
            if new_refresh:
                # persist new_refresh — token was rotated
                ...
            messages = await client.get_all_guest_messages()
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._access_token: str | None = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, refresh_token: str) -> str | None:
        """Exchange a refresh token for an access token.

        Returns the new refresh token if Beds24 rotated it, else None
        (caller should keep using the same refresh token).

        Raises Beds24AuthError on 401.
        """
        resp = await self._http.get(
            f"{BEDS24_BASE}/authentication/token",
            headers={"refreshToken": refresh_token},
        )
        if resp.status_code == 401:
            raise Beds24AuthError(
                "Beds24 refresh token rejected (401) — regenerate in Beds24 settings"
            )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["token"]
        logger.debug("beds24.authenticated expires_in=%s", data.get("expiresIn"))
        # refreshToken only present when Beds24 rotates the token
        return data.get("refreshToken") or None

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def get_messages(self, page: int = 1) -> tuple[list[dict], bool]:
        """Fetch one page of booking messages.

        Returns (messages, next_page_exists).
        """
        resp = await self._http.get(
            f"{BEDS24_BASE}/bookings/messages",
            headers=self._auth_headers(),
            params={"page": page},
        )
        resp.raise_for_status()
        body = resp.json()
        data: list[dict] = body.get("data", [])
        next_exists: bool = body.get("pages", {}).get("nextPageExists", False)
        return data, next_exists

    async def get_all_guest_messages(self) -> list[dict]:
        """Fetch all pages and return all messages (guest + host)."""
        all_msgs: list[dict] = []
        page = 1
        while True:
            msgs, has_next = await self.get_messages(page=page)
            all_msgs.extend(msgs)
            if not has_next:
                break
            page += 1
        return all_msgs

    # ------------------------------------------------------------------
    # Bookings
    # ------------------------------------------------------------------

    async def get_bookings(self, booking_ids: list[int]) -> list[dict]:
        """Batch-fetch booking details for a list of booking IDs.

        Returns a list of booking dicts (may be shorter than input if some
        IDs are not found).
        """
        if not booking_ids:
            return []
        resp = await self._http.get(
            f"{BEDS24_BASE}/bookings",
            headers=self._auth_headers(),
            params={"ids": ",".join(str(b) for b in booking_ids)},
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    async def get_properties(self) -> list[dict]:
        """Return all Beds24 properties — used by discover_beds24_properties.py."""
        resp = await self._http.get(
            f"{BEDS24_BASE}/properties",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        body = resp.json()
        return body.get("data", []) if isinstance(body, dict) else body

    # ------------------------------------------------------------------
    # Replies
    # ------------------------------------------------------------------

    async def post_message(self, booking_id: int, message: str) -> None:
        """Send a reply to a guest via Beds24 POST /bookings/messages."""
        resp = await self._http.post(
            f"{BEDS24_BASE}/bookings/messages",
            headers=self._auth_headers(),
            json=[{"bookingId": booking_id, "message": message}],
        )
        if not resp.is_success:
            logger.error(
                "beds24.post_message_failed booking_id=%s status=%s body=%s",
                booking_id,
                resp.status_code,
                resp.text,
            )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        if self._access_token is None:
            raise RuntimeError("Beds24Client: call authenticate() before API requests")
        return {"token": self._access_token}
