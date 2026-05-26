"""
WebSocket client with persistent connection and exponential backoff reconnect.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from client.config import SERVER_URI, WS_MAX_BACKOFF_S, WS_MAX_RETRIES

logger = logging.getLogger(__name__)


class ConnectionFailed(Exception):
    """Raised after all reconnect attempts are exhausted."""


class WSClient:
    """Persistent WebSocket client with auto-reconnect.

    Usage::

        client = WSClient()
        await client.connect()
        await client.send({"event": "final_transcript", "text": "hello"})
        msg = await client.recv()
        await client.close()
    """

    def __init__(self, uri: str = SERVER_URI) -> None:
        self._uri = uri
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._closed = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish the WebSocket connection (with backoff on failure)."""
        await self._reconnect_with_backoff()

    async def send(self, message: dict) -> None:
        """Serialise message to JSON and send over the WebSocket."""
        if self._ws is None:
            raise ConnectionFailed("Not connected.")
        try:
            await self._ws.send(json.dumps(message, ensure_ascii=False))
        except (ConnectionClosed, WebSocketException) as exc:
            logger.warning("WSClient send failed: %s — reconnecting…", exc)
            await self._reconnect_with_backoff()
            await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def recv(self) -> dict:
        """Receive one JSON message from the server."""
        if self._ws is None:
            raise ConnectionFailed("Not connected.")
        try:
            raw = await self._ws.recv()
            return json.loads(raw)
        except (ConnectionClosed, WebSocketException) as exc:
            logger.warning("WSClient recv failed: %s — reconnecting…", exc)
            await self._reconnect_with_backoff()
            raw = await self._ws.recv()
            return json.loads(raw)

    async def close(self) -> None:
        """Close the WebSocket connection gracefully."""
        self._closed = True
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
            logger.info("WSClient connection closed.")

    # ------------------------------------------------------------------
    # Internal reconnect logic
    # ------------------------------------------------------------------

    async def _reconnect_with_backoff(self) -> None:
        """Try to (re)connect with exponential backoff.

        Delay formula: min(2^attempt, WS_MAX_BACKOFF_S) seconds.
        Raises ConnectionFailed after WS_MAX_RETRIES failed attempts.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(1, WS_MAX_RETRIES + 1):
            try:
                self._ws = await websockets.connect(self._uri)
                logger.info("WSClient connected to %s (attempt %d).", self._uri, attempt)
                return
            except Exception as exc:
                last_exc = exc
                delay = min(2 ** attempt, WS_MAX_BACKOFF_S)
                logger.warning(
                    "WSClient connection attempt %d/%d failed: %s. Retrying in %ds…",
                    attempt,
                    WS_MAX_RETRIES,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        raise ConnectionFailed(
            f"Could not connect to {self._uri} after {WS_MAX_RETRIES} attempts."
        ) from last_exc
