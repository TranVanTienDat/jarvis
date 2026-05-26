"""
Google Gemini LLM provider.

Uses the official google-genai SDK with native async streaming.
Docs: https://ai.google.dev/gemini-api/docs
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from google import genai
from google.genai import types

from server.llms.base import BaseLLMService, LLMError
from server.models.schemas import ConversationMessage

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "Bạn là trợ lý giọng nói thông minh cho hệ thống nhà thông minh. "
    "Trả lời ngắn gọn, tự nhiên bằng tiếng Việt. "
    "Khi điều khiển thiết bị thành công, xác nhận ngắn gọn. "
    "Khi có lỗi, giải thích thân thiện và đề xuất giải pháp."
)


class GeminiLLMService(BaseLLMService):
    """Streams tokens from Google Gemini via google-genai SDK.

    Args:
        api_key:       Gemini API key (``GEMINI_API_KEY``).
        model:         Model name, e.g. ``"gemini-1.5-flash"``,
                       ``"gemini-2.0-flash"``.
        system_prompt: Override the default Vietnamese smart-home prompt.
        temperature:   Sampling temperature (0.0 – 2.0).
        max_tokens:    Maximum output tokens.

    Example::

        llm = GeminiLLMService(api_key=os.getenv("GEMINI_API_KEY"))
        async for token in llm.stream(messages):
            ...
    """

    provider_name = "gemini"
    default_model = "gemini-1.5-flash"  # fallback if GEMINI_MODEL is unset

    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str = _DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        self._client = genai.Client(api_key=api_key)
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
        contents = self._build_contents(messages)

        try:
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=self.default_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=self._system_prompt,
                    temperature=self._temperature,
                    max_output_tokens=self._max_tokens,
                ),
            ):
                if chunk.text:
                    yield chunk.text

        except Exception as exc:
            logger.error("GeminiLLMService error: %s", exc)
            raise LLMError(f"Gemini API error: {exc}") from exc

    @staticmethod
    def _build_contents(messages: list[ConversationMessage]) -> list[dict]:
        """Convert ConversationMessage list → Gemini contents format.

        Gemini has no native ``system`` role in contents; system messages
        are wrapped as model turns so the conversation stays valid.
        """
        result = []
        for msg in messages:
            if msg.role == "system":
                result.append({
                    "role": "model",
                    "parts": [{"text": f"[Hệ thống: {msg.content}]"}],
                })
            elif msg.role == "user":
                result.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == "assistant":
                result.append({"role": "model", "parts": [{"text": msg.content}]})
        return result
