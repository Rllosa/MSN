"""IMAP ingestion worker unit tests — all IMAP calls mocked, no live server."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.imap import (
    _poll_once,
    _run_worker,
    start_imap_worker,
    stop_imap_worker,
)


def _fake_settings() -> MagicMock:
    """Return a minimal Settings-like mock for unit tests."""
    s = MagicMock()
    s.imap_host = "imap.example.com"
    s.imap_port = 993
    s.imap_user = "user"
    s.imap_password = "pass"
    s.imap_poll_interval_seconds = 30
    return s


def _make_client(uids: list[bytes], raw_message: bytes = b"raw") -> MagicMock:
    """Build a minimal aioimaplib mock that returns the given unseen UIDs."""
    client = MagicMock()
    client.select = AsyncMock(return_value=("OK", [b"INBOX"]))
    # search returns ("OK", [b"1 2 3"]) or ("OK", [b""]) when no results
    uid_string = b" ".join(uids) if uids else b""
    client.search = AsyncMock(return_value=("OK", [uid_string]))
    # fetch returns ("OK", [b"..headers..", b"<raw message bytes>", b")"])
    client.fetch = AsyncMock(return_value=("OK", [b"..headers..", raw_message, b")"]))
    client.store = AsyncMock(return_value=("OK", []))
    return client


# ---------------------------------------------------------------------------
# _poll_once tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_once_no_unseen() -> None:
    """When INBOX has no UNSEEN messages, on_email is never called."""
    client = _make_client(uids=[])
    on_email = AsyncMock()

    await _poll_once(client, on_email)

    on_email.assert_not_called()
    client.store.assert_not_called()


@pytest.mark.asyncio
async def test_poll_once_fetches_emails() -> None:
    """Two UNSEEN UIDs → on_email called twice, both marked SEEN."""
    raw = b"From: test@example.com\r\n\r\nHello"
    client = _make_client(uids=[b"1", b"2"], raw_message=raw)
    on_email = AsyncMock()

    await _poll_once(client, on_email)

    assert on_email.call_count == 2
    on_email.assert_called_with(raw)
    assert client.store.call_count == 2
    # Verify SEEN flag is applied to both UIDs
    seen_uids = {call.args[0] for call in client.store.call_args_list}
    assert seen_uids == {b"1", b"2"}


# ---------------------------------------------------------------------------
# _run_worker tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_worker_stops_on_cancel() -> None:
    """CancelledError causes _run_worker to return cleanly without re-raising."""
    on_email = AsyncMock()

    with patch("app.workers.imap.get_settings", return_value=_fake_settings()):
        with patch("app.workers.imap.aioimaplib.IMAP4_SSL") as mock_cls:
            instance = MagicMock()
            instance.wait_hello_from_server = AsyncMock(
                side_effect=asyncio.CancelledError
            )
            mock_cls.return_value = instance

            # _run_worker must return (not raise) when cancelled
            await _run_worker(on_email)


@pytest.mark.asyncio
async def test_run_worker_retries_on_error() -> None:
    """Connection error → logs, sleeps, retries. Second attempt cancelled cleanly."""
    on_email = AsyncMock()
    call_count = 0

    with patch("app.workers.imap.get_settings", return_value=_fake_settings()):
        with patch("app.workers.imap.aioimaplib.IMAP4_SSL") as mock_cls:
            with patch(
                "app.workers.imap.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:

                def _side_effect(*_: object, **__: object) -> MagicMock:
                    nonlocal call_count
                    call_count += 1
                    instance = MagicMock()
                    if call_count == 1:
                        instance.wait_hello_from_server = AsyncMock(
                            side_effect=ConnectionRefusedError("IMAP down")
                        )
                    else:
                        instance.wait_hello_from_server = AsyncMock(
                            side_effect=asyncio.CancelledError
                        )
                    return instance

                mock_cls.side_effect = _side_effect

                await _run_worker(on_email)

    # sleep was called once (the backoff before retry)
    assert mock_sleep.call_count >= 1
    # connected twice: first failed, second cancelled cleanly
    assert call_count == 2


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_stop_worker() -> None:
    """start_imap_worker creates a running task; stop_imap_worker cancels cleanly."""

    async def _hang(*_: object, **__: object) -> None:
        await asyncio.sleep(9999)

    with patch("app.workers.imap.aioimaplib.IMAP4_SSL") as mock_cls:
        instance = MagicMock()
        instance.wait_hello_from_server = AsyncMock(side_effect=asyncio.CancelledError)
        mock_cls.return_value = instance

        start_imap_worker(on_email=_hang)

        import app.workers.imap as imap_module

        assert imap_module._worker_task is not None
        assert not imap_module._worker_task.done()

        await stop_imap_worker()

        assert imap_module._worker_task is None
