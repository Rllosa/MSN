"""Beds24 v2 API async client.

Beds24 is a channel manager that aggregates Airbnb + Booking.com confirmed bookings.
Auth uses a rotating refresh token: every call to /authentication/setup returns a new
refresh token that must be persisted immediately (the old one is invalidated).

Reference: https://beds24.com/api/v2
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

BEDS24_BASE = "https://beds24.com/api/v2"


class Beds24AuthError(Exception):
    """Raised when Beds24 rejects the refresh token or returns authenticated=False."""


class Beds24Client:
    """Async Beds24 v2 API client.

    Usage:
        async with httpx.AsyncClient(timeout=30) as http:
            client = Beds24Client(http)
            new_refresh_token = await client.authenticate(refresh_token)
            # persist new_refresh_token before proceeding
            messages = await client.get_inbox()
    """

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http
        self._access_token: str | None = None

    async def authenticate(self, refresh_token: str) -> str:
        """Exchange refresh token for a short-lived access token.

        Returns the new refresh token — caller MUST persist it before the next call.
        Beds24 rotates the refresh token on every authentication request.
        """
        resp = await self._http.get(
            f"{BEDS24_BASE}/authentication/setup",
            headers={"token": refresh_token},
        )
        if resp.status_code == 401:
            raise Beds24AuthError(
                "Beds24 refresh token rejected (401) — regenerate in Beds24 settings"
            )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("authenticated"):
            raise Beds24AuthError(f"Beds24 auth failed: {data}")
        self._access_token = data["token"]
        new_refresh_token: str = data["refreshToken"]
        logger.debug("beds24.authenticated expires_in=%s", data.get("expiresIn"))
        return new_refresh_token

    def _auth_headers(self) -> dict[str, str]:
        if self._access_token is None:
            raise RuntimeError("Beds24Client: call authenticate() before API requests")
        return {"token": self._access_token}

    async def get_inbox(self) -> list[dict]:
        """Return all inbox messages from Beds24.

        The worker tracks seen message IDs for deduplication (SOLO-111).
        """
        resp = await self._http.get(
            f"{BEDS24_BASE}/inbox",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json() if resp.text.strip() else []

    async def get_properties(self) -> list[dict]:
        """Return all Beds24 properties — used by discover_beds24_properties.py."""
        resp = await self._http.get(
            f"{BEDS24_BASE}/properties",
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json() if resp.text.strip() else []
