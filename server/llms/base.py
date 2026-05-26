"""
Abstract base class for all LLM providers.

Every provider must implement:
    stream() — async generator yielding token strings
    close()  — release any held resources (optional)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from server.models.schemas import ConversationMessage


class LLMError(Exception):
    """Raised when an LLM provider returns an error or times out."""


class BaseLLMService(ABC):
    """Common interface for all LLM providers.

    Usage::

        llm: BaseLLMService = SomeProvider(...)
        async for token in llm.stream(messages):
            print(token, end="", flush=True)
        await llm.close()
    """

    provider_name: str = "unknown"
    default_model: str = ""

    @abstractmethod
    async def stream(
        self,
        messages: list[ConversationMessage],
        system_context: str = "",
    ) -> AsyncIterator[str]:
        """Stream response tokens from the LLM.

        Args:
            messages:       Full conversation history including the latest
                            user message.
            system_context: Optional extra context injected before the last
                            user turn (e.g. IoT device state).
        Yields:
            Token strings as they arrive.
        Raises:
            LLMError: on any provider-level failure.
        """
        raise NotImplementedError
        yield  # pragma: no cover

    async def close(self) -> None:
        """Release provider resources (override if needed)."""

    # ------------------------------------------------------------------ #
    # Shared helpers                                                       #
    # ------------------------------------------------------------------ #

    def _inject_system_context(
        self,
        messages: list[ConversationMessage],
        system_context: str,
    ) -> list[ConversationMessage]:
        """Return a copy of messages with system_context injected as a
        system message just before the last user message."""
        if not system_context:
            return messages

        result = list(messages)
        last_user_idx = next(
            (i for i in range(len(result) - 1, -1, -1) if result[i].role == "user"),
            None,
        )
        if last_user_idx is not None:
            result.insert(
                last_user_idx,
                ConversationMessage(
                    role="system",
                    content=f"[Ngữ cảnh hiện tại: {system_context}]",
                ),
            )
        return result

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"provider={self.provider_name!r}, "
            f"model={self.default_model!r})"
        )
