"""
Error classifier for LLM fallback chain.

Classifies LLMError instances into ErrorKind.FALLBACK (skip to next provider)
or ErrorKind.RETRY (retry same provider with backoff).
"""
from __future__ import annotations

import asyncio
from enum import Enum

from server.llms.base import LLMError


class ErrorKind(Enum):
    FALLBACK = "fallback"  # skip current provider, try next
    RETRY = "retry"        # retry same provider with exponential backoff


# ── Pattern sets (all matched case-insensitively) ─────────────────────────────

_FALLBACK_403_PATTERNS = frozenset({
    "403", "forbidden", "invalid api key", "invalid_api_key",
    "authentication", "unauthorized", "permission denied",
})

_FALLBACK_429_PATTERNS = frozenset({
    "429", "rate limit", "rate_limit", "quota exceeded", "quota_exceeded",
    "too many requests", "resource exhausted",
})

_FALLBACK_TOKEN_PATTERNS = frozenset({
    "context length", "context_length", "token limit", "token_limit",
    "maximum context", "max tokens", "max_tokens",
    "input too long", "content too long",
})

_FALLBACK_TIMEOUT_PATTERNS = frozenset({"timeout"})

_RETRY_5XX_PATTERNS = frozenset({
    "500", "502", "503", "504",
    "internal server error", "bad gateway",
    "service unavailable", "gateway timeout", "server error",
})

_RETRY_CONNECTION_PATTERNS = frozenset({
    "connection reset", "connection error", "connection refused",
    "connection aborted", "broken pipe", "network error",
})

# TTS reason strings per error category
_REASON_403 = "không có quyền truy cập"
_REASON_429 = "đã hết quota"
_REASON_TOKEN = "đã hết token"
_REASON_TIMEOUT = "không phản hồi"
_REASON_DEFAULT = "gặp sự cố"


def _msg_lower(error: LLMError) -> str:
    return str(error).lower()


def _matches_any(text: str, patterns: frozenset[str]) -> bool:
    return any(p in text for p in patterns)


def _is_timeout_exc(error: LLMError) -> bool:
    """Check if the original cause is a timeout exception."""
    cause = error.__cause__
    return isinstance(cause, (asyncio.TimeoutError,))


class ErrorClassifier:
    """Classifies LLMError into FALLBACK or RETRY kind.

    Rules (evaluated in order):
    1. 403 / auth patterns          → FALLBACK
    2. 429 / rate-limit patterns    → FALLBACK
    3. context-length / token limit → FALLBACK
    4. timeout keyword or cause     → FALLBACK
    5. 5xx / server-error patterns  → RETRY
    6. connection-reset patterns    → RETRY
    7. conflict (both match)        → FALLBACK wins
    8. default (no match)           → FALLBACK (fail-safe)
    """

    def classify(self, error: LLMError) -> ErrorKind:
        """Return the ErrorKind for the given LLMError."""
        msg = _msg_lower(error)

        is_fallback = (
            _matches_any(msg, _FALLBACK_403_PATTERNS)
            or _matches_any(msg, _FALLBACK_429_PATTERNS)
            or _matches_any(msg, _FALLBACK_TOKEN_PATTERNS)
            or _matches_any(msg, _FALLBACK_TIMEOUT_PATTERNS)
            or _is_timeout_exc(error)
        )

        is_retry = (
            _matches_any(msg, _RETRY_5XX_PATTERNS)
            or _matches_any(msg, _RETRY_CONNECTION_PATTERNS)
        )

        # FALLBACK wins on conflict; default (neither) → FALLBACK
        if is_fallback or not is_retry:
            return ErrorKind.FALLBACK
        return ErrorKind.RETRY

    def get_tts_reason(self, error: LLMError) -> str:
        """Return a friendly Vietnamese reason string for TTS notification."""
        msg = _msg_lower(error)

        if _matches_any(msg, _FALLBACK_403_PATTERNS):
            return _REASON_403
        if _matches_any(msg, _FALLBACK_429_PATTERNS):
            return _REASON_429
        if _matches_any(msg, _FALLBACK_TOKEN_PATTERNS):
            return _REASON_TOKEN
        if _matches_any(msg, _FALLBACK_TIMEOUT_PATTERNS) or _is_timeout_exc(error):
            return _REASON_TIMEOUT
        return _REASON_DEFAULT
