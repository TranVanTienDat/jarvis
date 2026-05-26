"""
OpenRouter LLM provider.

OpenRouter is a unified gateway to 200+ models (Claude, GPT, Llama, Mistral…)
via a single OpenAI-compatible endpoint.
Docs: https://openrouter.ai/docs
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

_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterLLMService(BaseLLMService):
    """Streams tokens via OpenRouter's OpenAI-compatible endpoint.

    Args:
        api_key:       OpenRouter API key (``OPENROUTER_API_KEY``).
        model:         Any model slug from openrouter.ai/models, e.g.
                       ``"anthropic/claude-3.5-sonnet"``,
                       ``"meta-llama/llama-3.1-8b-instruct:free"``.
        system_prompt: Override the default system prompt.
        temperature:   Sampling temperature (0.0 – 2.0).
        max_tokens:    Maximum output tokens.
        site_url:      Your app URL — shown in OpenRouter dashboard.
        site_name:     Your app name — shown in OpenRouter dashboard.

    Example::

        llm = OpenRouterLLMService(
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model="anthropic/claude-3.5-sonnet",
        )
        async for token in llm.stream(messages):
            ...
    """

    provider_name = "openrouter"
    default_model = "meta-llama/llama-3.1-8b-instruct:free"  # fallback if OPENROUTER_MODEL is unset

    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 512,
        site_url: str = "https://zenta.local",
        site_name: str = "Zenta",
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=_BASE_URL,
            default_headers={
                "HTTP-Referer": site_url,
                "X-Title": site_name,
            },
        )
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
            logger.error("OpenRouterLLMService timeout: %s", exc)
            raise LLMError(f"OpenRouter timeout: {exc}") from exc
        except APIError as exc:
            logger.error("OpenRouterLLMService API error: %s", exc)
            raise LLMError(f"OpenRouter API error: {exc}") from exc
        except Exception as exc:
            logger.error("OpenRouterLLMService unexpected error: %s", exc)
            raise LLMError(f"OpenRouter error: {exc}") from exc

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
