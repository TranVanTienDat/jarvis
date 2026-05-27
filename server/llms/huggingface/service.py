"""
Hugging Face Inference API LLM provider.

Uses the Hugging Face serverless Inference API (text-generation task).
Supports streaming via the huggingface_hub InferenceClient.
Docs: https://huggingface.co/docs/api-inference/tasks/text-generation
      https://huggingface.co/docs/huggingface_hub/guides/inference
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from huggingface_hub import AsyncInferenceClient
from huggingface_hub.errors import HfHubHTTPError

from server.llms.base import BaseLLMService, LLMError
from server.models.schemas import ConversationMessage
from server.prompts import DEFAULT_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class HuggingFaceLLMService(BaseLLMService):
    """Streams tokens from Hugging Face Inference API.

    Uses the chat_completion endpoint (OpenAI-compatible) available on
    models that support it (e.g. Llama, Mistral, Qwen, Phi).

    Args:
        api_key:       Hugging Face token (``HF_API_KEY``).
        model:         Model repo ID, e.g. ``"meta-llama/Llama-3.1-8B-Instruct"``,
                       ``"mistralai/Mistral-7B-Instruct-v0.3"``.
        system_prompt: Override the default system prompt.
        temperature:   Sampling temperature (0.0 – 2.0).
        max_tokens:    Maximum output tokens.

    Example::

        llm = HuggingFaceLLMService(
            api_key=os.getenv("HF_API_KEY"),
            model="meta-llama/Llama-3.1-8B-Instruct",
        )
        async for token in llm.stream(messages):
            ...
    """

    provider_name = "huggingface"
    default_model = "meta-llama/Llama-3.1-8B-Instruct"  # fallback if HF_MODEL is unset

    def __init__(
        self,
        api_key: str,
        model: str,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.7,
        max_tokens: int = 512,
    ) -> None:
        self._client = AsyncInferenceClient(
            model=model or self.__class__.default_model,
            token=api_key,
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
        hf_messages = self._build_messages(messages)

        try:
            stream = await self._client.chat_completion(
                messages=hf_messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        except HfHubHTTPError as exc:
            logger.error("HuggingFaceLLMService HTTP error: %s", exc)
            raise LLMError(f"Hugging Face API error: {exc}") from exc
        except Exception as exc:
            logger.error("HuggingFaceLLMService unexpected error: %s", exc)
            raise LLMError(f"Hugging Face error: {exc}") from exc

    async def close(self) -> None:
        # AsyncInferenceClient does not require explicit cleanup
        pass

    def _build_messages(self, messages: list[ConversationMessage]) -> list[dict]:
        """Convert ConversationMessage list → chat messages format."""
        result = [{"role": "system", "content": self._system_prompt}]
        for msg in messages:
            if msg.role == "system":
                result.append({"role": "system", "content": msg.content})
            elif msg.role == "user":
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                result.append({"role": "assistant", "content": msg.content})
        return result
