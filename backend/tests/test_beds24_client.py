"""Beds24 client unit tests — all httpx calls mocked, no live network."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.clients.beds24 import Beds24AuthError, Beds24Client

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_http() -> AsyncMock:
    return AsyncMock(spec=httpx.AsyncClient)


def _resp(data: object, status_code: int = 200) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = data
    r.text = json.dumps(data)
    r.raise_for_status = MagicMock()
    return r


# ---------------------------------------------------------------------------
# authenticate()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_success_returns_new_refresh_token() -> None:
    """Happy-path auth: access token stored, new refresh token returned."""
    http = _mock_http()
    http.get.return_value = _resp(
        {"token": "access-abc", "refreshToken": "refresh-xyz", "authenticated": True}
    )
    client = Beds24Client(http)

    new_token = await client.authenticate("old-refresh")

    assert new_token == "refresh-xyz"
    assert client._access_token == "access-abc"
    http.get.assert_called_once()
    assert "authentication/setup" in http.get.call_args.args[0]


@pytest.mark.asyncio
async def test_authenticate_raises_on_401() -> None:
    """401 response → Beds24AuthError (token revoked / expired)."""
    http = _mock_http()
    resp = _resp({}, status_code=401)
    resp.raise_for_status = MagicMock()  # don't raise from raise_for_status
    http.get.return_value = resp

    client = Beds24Client(http)
    with pytest.raises(Beds24AuthError, match="401"):
        await client.authenticate("bad-token")


@pytest.mark.asyncio
async def test_authenticate_raises_when_not_authenticated() -> None:
    """authenticated=False in response body → Beds24AuthError."""
    http = _mock_http()
    http.get.return_value = _resp({"authenticated": False, "error": "token invalid"})

    client = Beds24Client(http)
    with pytest.raises(Beds24AuthError):
        await client.authenticate("bad-token")


# ---------------------------------------------------------------------------
# get_inbox()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_inbox_returns_messages() -> None:
    """get_inbox() passes access token header and returns message list."""
    http = _mock_http()
    messages = [
        {"id": 1, "propId": 314537, "bookId": 999, "msg": "Hello"},
        {"id": 2, "propId": 314538, "bookId": 1000, "msg": "Hi there"},
    ]
    http.get.return_value = _resp(messages)

    client = Beds24Client(http)
    client._access_token = "access-abc"

    result = await client.get_inbox()

    assert result == messages
    call_args = http.get.call_args
    assert "inbox" in call_args.args[0]
    assert call_args.kwargs["headers"]["token"] == "access-abc"


@pytest.mark.asyncio
async def test_get_inbox_empty_response_returns_empty_list() -> None:
    """Empty body (no messages) → []."""
    http = _mock_http()
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = []
    resp.text = ""
    resp.raise_for_status = MagicMock()
    http.get.return_value = resp

    client = Beds24Client(http)
    client._access_token = "access-abc"

    result = await client.get_inbox()
    assert result == []


# ---------------------------------------------------------------------------
# get_properties()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_properties_returns_property_list() -> None:
    """get_properties() hits /properties and returns Beds24 property objects."""
    http = _mock_http()
    props = [
        {"propId": 314537, "propName": "Lagoon"},
        {"propId": 314538, "propName": "Sunrise"},
    ]
    http.get.return_value = _resp(props)

    client = Beds24Client(http)
    client._access_token = "access-abc"

    result = await client.get_properties()

    assert result == props
    assert "properties" in http.get.call_args.args[0]
