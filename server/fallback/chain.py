"""
FallbackChain — LLM provider fallback chain.

Tries providers in priority order. On transient errors (5xx, connection reset)
retries the same provider with exponential backoff. On permanent errors (403,
429, token limit, timeout) immediately falls back to the next provider and
fires a non-blocking TTS notification.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from fastapi import WebSocket

from server.llms.base import BaseLLMService, LLMError
from server.fallback.classifier import ErrorClassifier, ErrorKind
from server.fallback.notifier import FallbackNotifier
from server.models.schemas import ConversationMessage

logger = logging.getLogger("server.fallback")


class FallbackChain(BaseLLMService):
    """Wraps multiple LLM providers and falls back automatically on errors.

    Args:
        providers:      Ordered list of providers to try (highest priority first).
        notifier:       FallbackNotifier for TTS announcements.
        max_retry:      Max retries per provider on transient (RETRY) errors.
        retry_delay_s:  Base delay for exponential backoff (delay * 2^attempt).

    Usage::

        chain = FallbackChain(providers=[gemini, deepseek], notifier=notifier)
        chain.set_websocket(websocket)
        async for token in chain.stream(messages):
            ...
    """

    provider_name = "fallback_chain"
    default_model = ""

    def __init__(
        self,
        providers: list[BaseLLMService],
        notifier: FallbackNotifier,
        max_retry: int = 2,
        retry_delay_s: float = 1.0,
    ) -> None:
        self._providers = providers
        self._notifier = notifier
        self._max_retry = max_retry
        self._retry_delay_s = retry_delay_s
        self._classifier = ErrorClassifier()
        self._websocket: Optional[WebSocket] = None

    def set_websocket(self, websocket: WebSocket) -> None:
        """Inject the active WebSocket for TTS notifications.

        Call this before each ``stream()`` invocation.
        """
        self._websocket = websocket

    async def stream(
        self,
        messages: list[ConversationMessage],
        system_context: str = "",
    ) -> AsyncIterator[str]:
        """Stream tokens, falling back through providers on error.

        Raises:
            LLMError: if all providers fail or the provider list is empty.
        """
        if not self._providers:
            raise LLMError(
                "Không có provider nào được cấu hình: danh sách hoạt động rỗng"
            )

        # Track (provider_name, error_kind_label, error_msg, attempt_count)
        failures: list[tuple[str, str, str, int]] = []
        had_fallback = False

        for idx, provider in enumerate(self._providers):
            retry_count = 0

            while True:
                try:
                    async for token in provider.stream(messages, system_context):
                        yield token

                    # ── Success ──────────────────────────────────────────────
                    if had_fallback:
                        logger.info(
                            "[FallbackChain] %s succeeded after %d fallback(s)",
                            provider.provider_name,
                            len(failures),
                        )
                    return  # done — stop the generator

                except LLMError as exc:
                    kind = self._classifier.classify(exc)

                    if kind == ErrorKind.RETRY and retry_count < self._max_retry:
                        retry_count += 1
                        delay = self._retry_delay_s * (2 ** retry_count)
                        logger.debug(
                            "[FallbackChain] %s retry %d/%d, waiting %.2fs — %s",
                            provider.provider_name,
                            retry_count,
                            self._max_retry,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                        continue  # retry same provider

                    # ── Fallback ─────────────────────────────────────────────
                    total_attempts = 1 + retry_count
                    failures.append((
                        provider.provider_name,
                        kind.value.upper(),
                        str(exc),
                        total_attempts,
                    ))

                    next_provider = (
                        self._providers[idx + 1] if idx + 1 < len(self._providers) else None
                    )

                    logger.warning(
                        "[FallbackChain] %s failed (%s) after %d attempt(s) → %s | error: %s",
                        provider.provider_name,
                        kind.value.upper(),
                        total_attempts,
                        next_provider.provider_name if next_provider else "none (all exhausted)",
                        exc,
                    )

                    if next_provider and self._websocket:
                        reason = self._classifier.get_tts_reason(exc)
                        await self._notifier.notify_fallback(
                            provider.provider_name,
                            next_provider.provider_name,
                            reason,
                            self._websocket,
                        )

                    had_fallback = True
                    break  # move to next provider

        # ── All providers exhausted ───────────────────────────────────────────
        if self._websocket:
            await self._notifier.notify_all_failed(self._websocket)

        summary = _build_summary_message(failures)
        logger.error("[FallbackChain] All providers failed.\n%s", summary)
        raise LLMError(summary)

    async def close(self) -> None:
        """Close all providers, logging warnings for individual failures."""
        for provider in self._providers:
            try:
                await provider.close()
            except Exception as exc:
                logger.warning(
                    "[FallbackChain] Error closing provider %s: %s",
                    provider.provider_name,
                    exc,
                )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_summary_message(
    failures: list[tuple[str, str, str, int]],
) -> str:
    """Build a human-readable summary of all provider failures.

    Each entry is (provider_name, error_kind, error_msg, attempt_count).
    """
    n = len(failures)
    lines = [f"Tất cả {n} provider đều thất bại:"]
    for provider_name, kind, error_msg, attempts in failures:
        lines.append(
            f"  - {provider_name}: {kind} [{attempts} lần thử] — {error_msg}"
        )
    return "\n".join(lines)
