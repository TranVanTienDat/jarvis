"""
OpenAI LLM provider.

Supports all GPT models via the official OpenAI Chat Completions API.
Docs: https://platform.openai.com/docs/api-reference/chat
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI, APIError, APITimeoutError

from server.llms.base import BaseLLMService, LLMError
from server.models.schemas import ConversationMessage

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "Bạn là trợ lý giọng nói thông minh cho hệ thống nhà thông minh. "
    "Trả lời ngắn gọn, tự nhiên bằng tiếng Việt. "
    "Khi điều khiển thiết bị thành công, xác nhận ngắn gọn. "
    "Khi có lỗi, giải thích thân thiện và đề xuất giải pháp."
)


class OpenAILLMService(BaseLLMService):
    """Streams tokens from OpenAI GPT models.

    Args:
        api_key:       OpenAI API key (``OPENAI_API_KEY``).
        model:         Model name, e.g. ``"gpt-4o"``, ``"gpt-4o-mini"``.
        system_prompt: Override the default system prompt.
        temperature:   Sampling temperature (0.0 – 2.0).
        max_tokens:    Maximum output tokens.

    Example::

        llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
        async for token in llm.stream(messages):
            ...
    """

    provider_name = "openai"
    default_model = "gpt-4o-mini"  # fallback if OPENAI_MODEL is unset

    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self.default_model = model or self.__class__.default_model
        self._system_prompt = system_prompt
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def stream(
        self,
        messages: list[ConversationMessage],
        system_context: str = "",
    ) -> AsyncIterator[str]:
        messages = self._inject_system_context(messages, system_context)
        oai_messages = self._build_messages(messages)

        try:
            async with self._client.chat.completions.stream(
                model=self.default_model,
                messages=oai_messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            ) as stream:
                async for text in stream.text_stream:
                    if text:
                        yield text

        except APITimeoutError as exc:
            logger.error("OpenAILLMService timeout: %s", exc)
            raise LLMError(f"OpenAI timeout: {exc}") from exc
        except APIError as exc:
            logger.error("OpenAILLMService API error: %s", exc)
            raise LLMError(f"OpenAI API error: {exc}") from exc
        except Exception as exc:
            logger.error("OpenAILLMService unexpected error: %s", exc)
            raise LLMError(f"OpenAI error: {exc}") from exc

    async def close(self) -> None:
        await self._client.close()

    def _build_messages(self, messages: list[ConversationMessage]) -> list[dict]:
        """Convert ConversationMessage list → OpenAI messages format."""
        result = [{"role": "system", "content": self._system_prompt}]
        for msg in messages:
            if msg.role == "system":
                result.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                result.append({"role": "assistant", "content": msg.content})
        return result
