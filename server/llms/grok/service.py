"""
xAI Grok LLM provider.

Grok exposes an OpenAI-compatible Chat Completions endpoint.
Docs: https://docs.x.ai/api
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

_BASE_URL = "https://api.x.ai/v1"


class GrokLLMService(BaseLLMService):
    """Streams tokens from xAI Grok models.

    Args:
        api_key:       xAI API key (``XAI_API_KEY``).
        model:         Model name, e.g. ``"grok-3"``, ``"grok-3-mini"``.
        system_prompt: Override the default system prompt.
        temperature:   Sampling temperature (0.0 – 2.0).
        max_tokens:    Maximum output tokens.

    Example::

        llm = GrokLLMService(
            api_key=os.getenv("XAI_API_KEY"),
            model="grok-3-mini",
        )
        async for token in llm.stream(messages):
            ...
    """

    provider_name = "grok"
    default_model = "grok-3-mini"  # fallback if GROK_MODEL is unset

    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)
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
            logger.error("GrokLLMService timeout: %s", exc)
            raise LLMError(f"Grok timeout: {exc}") from exc
        except APIError as exc:
            logger.error("GrokLLMService API error: %s", exc)
            raise LLMError(f"Grok API error: {exc}") from exc
        except Exception as exc:
            logger.error("GrokLLMService unexpected error: %s", exc)
            raise LLMError(f"Grok error: {exc}") from exc

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
