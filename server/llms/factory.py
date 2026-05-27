"""
LLM provider factory.

Reads provider selection and all model/key config from ``server.config``,
which in turn reads from environment variables.

Supported values for ``LLM_PROVIDER`` env var:
    gemini        (default)
    openai
    openrouter
    grok
    together
    deepseek
    huggingface

Environment variables reference:

    Variable              | Provider     | Description
    ----------------------|--------------|-----------------------------
    LLM_PROVIDER          | all          | Which provider to use
    GEMINI_API_KEY        | gemini       | Google AI API key
    GEMINI_MODEL          | gemini       | e.g. gemini-2.0-flash
    OPENAI_API_KEY        | openai       | OpenAI API key
    OPENAI_MODEL          | openai       | e.g. gpt-4o, gpt-4o-mini
    OPENROUTER_API_KEY    | openrouter   | OpenRouter API key
    OPENROUTER_MODEL      | openrouter   | e.g. anthropic/claude-3.5-sonnet
    XAI_API_KEY           | grok         | xAI API key
    GROK_MODEL            | grok         | e.g. grok-3, grok-3-mini
    TOGETHER_API_KEY      | together     | Together AI API key
    TOGETHER_MODEL        | together     | e.g. meta-llama/Llama-3.3-70B-Instruct-Turbo
    DEEPSEEK_API_KEY      | deepseek     | DeepSeek API key
    DEEPSEEK_MODEL        | deepseek     | e.g. deepseek-chat, deepseek-reasoner
    HF_API_KEY            | huggingface  | Hugging Face token
    HF_MODEL              | huggingface  | e.g. meta-llama/Llama-3.1-8B-Instruct
"""
from __future__ import annotations

import server.config as cfg
from server.llms.base import BaseLLMService


def create_llm_service() -> BaseLLMService:
    """Instantiate the LLM provider configured via ``LLM_PROVIDER``.

    Returns:
        A ready-to-use ``BaseLLMService`` instance.

    Raises:
        ValueError:  if ``LLM_PROVIDER`` is set to an unknown value.
        RuntimeError: if the required API key is missing.
    """
    provider = cfg.LLM_PROVIDER.lower().strip()

    if provider == "gemini":
        from server.llms.gemini import GeminiLLMService
        _require_key("GEMINI_API_KEY", cfg.GEMINI_API_KEY, provider)
        return GeminiLLMService(
            api_key=cfg.GEMINI_API_KEY,
            model=cfg.GEMINI_MODEL,
        )

    if provider == "openai":
        from server.llms.openai import OpenAILLMService
        _require_key("OPENAI_API_KEY", cfg.OPENAI_API_KEY, provider)
        return OpenAILLMService(
            api_key=cfg.OPENAI_API_KEY,
            model=cfg.OPENAI_MODEL,
        )

    if provider == "openrouter":
        from server.llms.openrouter import OpenRouterLLMService
        _require_key("OPENROUTER_API_KEY", cfg.OPENROUTER_API_KEY, provider)
        return OpenRouterLLMService(
            api_key=cfg.OPENROUTER_API_KEY,
            model=cfg.OPENROUTER_MODEL,
        )

    if provider == "grok":
        from server.llms.grok import GrokLLMService
        _require_key("XAI_API_KEY", cfg.XAI_API_KEY, provider)
        return GrokLLMService(
            api_key=cfg.XAI_API_KEY,
            model=cfg.GROK_MODEL,
        )

    if provider == "together":
        from server.llms.together import TogetherLLMService
        _require_key("TOGETHER_API_KEY", cfg.TOGETHER_API_KEY, provider)
        return TogetherLLMService(
            api_key=cfg.TOGETHER_API_KEY,
            model=cfg.TOGETHER_MODEL,
        )

    if provider == "deepseek":
        from server.llms.deepseek import DeepSeekLLMService
        _require_key("DEEPSEEK_API_KEY", cfg.DEEPSEEK_API_KEY, provider)
        return DeepSeekLLMService(
            api_key=cfg.DEEPSEEK_API_KEY,
            model=cfg.DEEPSEEK_MODEL,
        )

    if provider == "huggingface":
        from server.llms.huggingface import HuggingFaceLLMService
        _require_key("HF_API_KEY", cfg.HF_API_KEY, provider)
        return HuggingFaceLLMService(
            api_key=cfg.HF_API_KEY,
            model=cfg.HF_MODEL,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}. "
        "Valid options: gemini, openai, openrouter, grok, together, deepseek, huggingface"
    )


def _require_key(env_var: str, value: str, provider: str) -> None:
    if not value:
        raise RuntimeError(
            f"LLM_PROVIDER={provider!r} requires {env_var} to be set."
        )
