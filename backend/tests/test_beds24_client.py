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
async def test_authenticate_no_rotation_returns_none() -> None:
    """When Beds24 does not rotate, refreshToken absent → returns None."""
    http = _mock_http()
    http.get.return_value = _resp({"token": "access-abc", "expiresIn": 86400})
    client = Beds24Client(http)

    result = await client.authenticate("my-refresh")

    assert result is None
    assert client._access_token == "access-abc"
    call_kwargs = http.get.call_args
    assert "authentication/token" in call_kwargs.args[0]
    assert call_kwargs.kwargs["headers"]["refreshToken"] == "my-refresh"


@pytest.mark.asyncio
async def test_authenticate_with_rotation_returns_new_token() -> None:
    """When Beds24 rotates, refreshToken present → returns new refresh token."""
    http = _mock_http()
    http.get.return_value = _resp(
        {"token": "access-abc", "expiresIn": 86400, "refreshToken": "refresh-xyz"}
    )
    client = Beds24Client(http)

    result = await client.authenticate("old-refresh")

    assert result == "refresh-xyz"
    assert client._access_token == "access-abc"


@pytest.mark.asyncio
async def test_authenticate_raises_on_401() -> None:
    """401 response → Beds24AuthError."""
    http = _mock_http()
    resp = _resp({}, status_code=401)
    resp.raise_for_status = MagicMock()
    http.get.return_value = resp

    client = Beds24Client(http)
    with pytest.raises(Beds24AuthError, match="401"):
        await client.authenticate("bad-token")


# ---------------------------------------------------------------------------
# get_messages()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_messages_returns_data_and_pagination() -> None:
    """get_messages() returns (messages, has_next) correctly."""
    http = _mock_http()
    msgs = [
        {
            "id": 1,
            "bookingId": 100,
            "propertyId": 314537,
            "source": "guest",
            "message": "Hi",
        },
        {
            "id": 2,
            "bookingId": 101,
            "propertyId": 314538,
            "source": "host",
            "message": "Hello",
        },
    ]
    http.get.return_value = _resp(
        {
            "success": True,
            "data": msgs,
            "pages": {"nextPageExists": True, "nextPageLink": "..."},
        }
    )
    client = Beds24Client(http)
    client._access_token = "access-abc"

    data, has_next = await client.get_messages(page=1)

    assert data == msgs
    assert has_next is True
    call_args = http.get.call_args
    assert "bookings/messages" in call_args.args[0]
    assert call_args.kwargs["headers"]["token"] == "access-abc"


@pytest.mark.asyncio
async def test_get_all_guest_messages_returns_all_sources() -> None:
    """get_all_guest_messages() returns both guest and host messages."""
    http = _mock_http()
    msgs = [
        {"id": 1, "bookingId": 100, "source": "guest", "message": "Hi"},
        {"id": 2, "bookingId": 101, "source": "host", "message": "Hello"},
        {"id": 3, "bookingId": 102, "source": "guest", "message": "Question"},
    ]
    http.get.return_value = _resp(
        {
            "success": True,
            "data": msgs,
            "pages": {"nextPageExists": False, "nextPageLink": None},
        }
    )
    client = Beds24Client(http)
    client._access_token = "access-abc"

    result = await client.get_all_guest_messages()

    assert len(result) == 3
    sources = {m["source"] for m in result}
    assert sources == {"guest", "host"}


# ---------------------------------------------------------------------------
# get_bookings()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_bookings_batch_fetch() -> None:
    """get_bookings() passes comma-joined IDs and returns booking list."""
    http = _mock_http()
    bookings = [
        {"id": 100, "channel": "airbnb", "firstName": "Alice", "lastName": "Smith"},
        {"id": 101, "channel": "booking", "firstName": "Bob", "lastName": "Jones"},
    ]
    http.get.return_value = _resp({"success": True, "data": bookings})
    client = Beds24Client(http)
    client._access_token = "access-abc"

    result = await client.get_bookings([100, 101])

    assert result == bookings
    call_args = http.get.call_args
    assert "bookings" in call_args.args[0]
    assert "100,101" in call_args.kwargs["params"]["ids"]


@pytest.mark.asyncio
async def test_get_bookings_empty_list_returns_empty() -> None:
    """get_bookings([]) returns [] without making an API call."""
    http = _mock_http()
    client = Beds24Client(http)
    client._access_token = "access-abc"

    result = await client.get_bookings([])

    assert result == []
    http.get.assert_not_called()


# ---------------------------------------------------------------------------
# get_properties()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_properties_returns_property_list() -> None:
    """get_properties() hits /properties and returns property objects."""
    http = _mock_http()
    props = [
        {"id": 314537, "name": "Lagoon  (Apt1) Sea view"},
        {"id": 314538, "name": "Horizon (Apt3)"},
    ]
    http.get.return_value = _resp({"success": True, "data": props})
    client = Beds24Client(http)
    client._access_token = "access-abc"

    result = await client.get_properties()

    assert result == props
    assert "properties" in http.get.call_args.args[0]


# ---------------------------------------------------------------------------
# post_message()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_message_sends_array_body() -> None:
    """post_message() POSTs a JSON array with bookingId and message."""
    http = _mock_http()
    http.post.return_value = _resp({"success": True}, status_code=200)
    client = Beds24Client(http)
    client._access_token = "access-abc"

    await client.post_message(12345, "Hello guest!")

    call_kwargs = http.post.call_args
    assert "bookings/messages" in call_kwargs.args[0]
    body = call_kwargs.kwargs["json"]
    assert isinstance(body, list), "Beds24 requires an array body"
    assert body[0]["bookingId"] == 12345
    assert body[0]["message"] == "Hello guest!"
