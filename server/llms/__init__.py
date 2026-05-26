"""
LLM provider package.

Each sub-folder is one provider:
    gemini/      — Google Gemini (google-genai SDK)
    openai/      — OpenAI GPT models
    openrouter/  — OpenRouter multi-model gateway
    grok/        — xAI Grok
    together/    — Together AI open-source models

Use ``create_llm_service()`` to get the provider configured via
the ``LLM_PROVIDER`` environment variable (default: ``"gemini"``).
"""
from server.llms.base import BaseLLMService, LLMError
from server.llms.factory import create_llm_service

__all__ = [
    "BaseLLMService",
    "LLMError",
    "create_llm_service",
]
