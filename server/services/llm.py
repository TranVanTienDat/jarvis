"""
LLM service — Gemini streaming via google-genai SDK.
Yields tokens as they arrive from the API.
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from google import genai
from google.genai import types

from server.config import GEMINI_API_KEY, GEMINI_MODEL
from server.models.schemas import ConversationMessage

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ban la tro ly giong noi thong minh cho he thong nha thong minh. "
    "Tra loi ngan gon, tu nhien bang tieng Viet. "
    "Khi dieu khien thiet bi thanh cong, xac nhan ngan gon. "
    "Khi co loi, giai thich than thien va de xuat giai phap."
)


class LLMError(Exception):
    """Raised when the Gemini API returns an error or times out."""


class LLMService:
    """Streams tokens from Gemini using google-genai SDK.

    Usage::

        llm = LLMService()
        async for token in llm.stream(messages):
            print(token, end="", flush=True)
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=GEMINI_API_KEY)

    async def stream(
        self,
        messages: list[ConversationMessage],
        system_context: str = "",
    ) -> AsyncIterator[str]:
        """Stream tokens from Gemini.

        Args:
            messages:       Conversation history + current user message.
            system_context: Optional extra context injected before last user turn.

        Yields:
            Token strings as they arrive.

        Raises:
            LLMError: on API failure.
        """
        contents = self._build_contents(messages, system_context)

        try:
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                ),
            ):
                text = chunk.text
                if text:
                    yield text

        except Exception as exc:
            logger.error("LLMService stream error: %s", exc)
            raise LLMError(f"Gemini API error: {exc}") from exc

    @staticmethod
    def _build_contents(
        messages: list[ConversationMessage],
        system_context: str,
    ) -> list[dict]:
        """Convert ConversationMessage list to Gemini contents format."""
        result = []
        for msg in messages:
            if msg.role == "system":
                result.append({"role": "model", "parts": [{"text": f"[He thong: {msg.content}]"}]})
            elif msg.role == "user":
                result.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == "assistant":
                result.append({"role": "model", "parts": [{"text": msg.content}]})

        # Inject extra system context before the last user message if provided
        if system_context and result and result[-1]["role"] == "user":
            last_user = result.pop()
            result.append({"role": "model", "parts": [{"text": f"[Ngu canh: {system_context}]"}]})
            result.append(last_user)

        return result
