"""
Conversation context manager — stores per-session history in Redis.
Implements a sliding window of MAX_HISTORY turns.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from server.config import REDIS_URL, SESSION_HISTORY_MAX

logger = logging.getLogger(__name__)

_KEY_TEMPLATE = "session:{session_id}:history"


class ContextManager:
    """Manages short-term conversation history in Redis.

    Gracefully degrades (returns empty history, logs WARNING) when Redis
    is unavailable so the rest of the pipeline can continue.
    """

    def __init__(self, redis_url: str = REDIS_URL) -> None:
        self._redis_url = redis_url
        self._redis: Optional[object] = None  # redis.asyncio.Redis

    async def connect(self) -> None:
        """Open the Redis connection pool."""
        try:
            import redis.asyncio as aioredis  # type: ignore[import]

            self._redis = aioredis.from_url(
                self._redis_url, encoding="utf-8", decode_responses=True
            )
            # Verify connectivity
            await self._redis.ping()
            logger.info("ContextManager connected to Redis at %s", self._redis_url)
        except Exception as exc:
            logger.warning(
                "ContextManager: Redis unavailable (%s). Running without history.", exc
            )
            self._redis = None

    async def get_history(self, session_id: str) -> list[dict]:
        """Return the conversation history for a session (newest last).

        Returns an empty list if Redis is unavailable.
        """
        if self._redis is None:
            return []
        key = _KEY_TEMPLATE.format(session_id=session_id)
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return []
            return json.loads(raw)
        except Exception as exc:
            logger.warning("ContextManager.get_history error: %s", exc)
            return []

    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Append a message and enforce the sliding window (MAX_HISTORY turns).

        A "turn" is one user message + one assistant message, but here we
        store individual messages and cap at SESSION_HISTORY_MAX entries.
        """
        if self._redis is None:
            return
        key = _KEY_TEMPLATE.format(session_id=session_id)
        try:
            history = await self.get_history(session_id)
            history.append({"role": role, "content": content})
            # Sliding window: keep only the most recent MAX_HISTORY messages
            if len(history) > SESSION_HISTORY_MAX:
                history = history[-SESSION_HISTORY_MAX:]
            await self._redis.set(key, json.dumps(history, ensure_ascii=False))
        except Exception as exc:
            logger.warning("ContextManager.add_message error: %s", exc)

    async def clear_session(self, session_id: str) -> None:
        """Delete the history key for a session."""
        if self._redis is None:
            return
        key = _KEY_TEMPLATE.format(session_id=session_id)
        try:
            await self._redis.delete(key)
            logger.debug("ContextManager: cleared history for session %s", session_id)
        except Exception as exc:
            logger.warning("ContextManager.clear_session error: %s", exc)

    async def close(self) -> None:
        """Close the Redis connection."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
            self._redis = None
