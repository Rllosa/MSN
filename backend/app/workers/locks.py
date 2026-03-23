"""Shared asyncio locks for inter-worker coordination."""

from __future__ import annotations

import asyncio

# Held by the archive sweeper while running SQL archive queries.
# The Beds24 poller acquires this before each poll cycle so that
# a concurrent last_message_at update cannot cause eligible
# conversations to slip through the sweep.
archive_lock = asyncio.Lock()
