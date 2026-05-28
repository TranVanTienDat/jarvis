"""
LLM provider factory.

Reads provider selection and all model/key config from ``server.config``,
which in turn reads from environment variables.

Single-provider mode (default):
    Set ``LLM_PROVIDER`` to one of the supported values below.

Fallback-chain mode:
    Set ``LLM_PROVIDER_ORDER`` to a comma-separated list of providers in
    priority order (e.g. ``gemini,deepseek,grok``).  When set, the factory
    returns a ``FallbackChain`` that automatically tries each provider in
    order, retrying transient errors and falling back on permanent ones.

Supported provider names:
    gemini | openai | openrouter | grok | together | deepseek | huggingface

Environment variables reference:

    Variable              | Provider     | Description
    ----------------------|--------------|-----------------------------
    LLM_PROVIDER          | all          | Single provider (ignored when LLM_PROVIDER_ORDER is set)
    LLM_PROVIDER_ORDER    | all          | Comma-separated fallback priority list
    LLM_RETRY_MAX         | all          | Max retries on transient errors (default: 2)
    LLM_RETRY_DELAY_S     | all          | Exponential backoff base delay in seconds (default: 1.0)
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

import logging

import server.config as cfg
from server.llms.base import BaseLLMService

logger = logging.getLogger(__name__)


def create_llm_service() -> BaseLLMService:
    """Instantiate the configured LLM service.

    Returns a ``FallbackChain`` when ``LLM_PROVIDER_ORDER`` is set,
    otherwise returns a single provider as before.

    Raises:
        ValueError:   if a provider name is unknown.
        RuntimeError: if a required API key is missing.
    """
    if cfg.LLM_PROVIDER_ORDER.strip():
        return _create_fallback_chain()
    return _create_single_provider(cfg.LLM_PROVIDER)


# ── Fallback chain ────────────────────────────────────────────────────────────

def _create_fallback_chain() -> BaseLLMService:
    """Build a FallbackChain from LLM_PROVIDER_ORDER."""
    from server.fallback import FallbackChain
    from server.fallback.notifier import FallbackNotifier
    from server.services.tts import TTSService

    raw_order = cfg.LLM_PROVIDER_ORDER
    names = [p.strip() for p in raw_order.split(",") if p.strip()]

    providers: list[BaseLLMService] = []
    for name in names:
        try:
            svc = _create_single_provider(name)
            providers.append(svc)
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "FallbackChain: skipping provider %r — %s", name, exc
            )

    tts = TTSService()
    notifier = FallbackNotifier(tts)
    return FallbackChain(
        providers=providers,
        notifier=notifier,
        max_retry=cfg.LLM_RETRY_MAX,
        retry_delay_s=cfg.LLM_RETRY_DELAY_S,
    )


# ── Single provider ───────────────────────────────────────────────────────────

def _create_single_provider(provider: str) -> BaseLLMService:
    """Instantiate a single LLM provider by name.

    Raises:
        ValueError:   if ``provider`` is not a known name.
        RuntimeError: if the required API key is missing.
    """
    name = provider.lower().strip()

    if name == "gemini":
        from server.llms.gemini import GeminiLLMService
        _require_key("GEMINI_API_KEY", cfg.GEMINI_API_KEY, name)
        return GeminiLLMService(api_key=cfg.GEMINI_API_KEY, model=cfg.GEMINI_MODEL)

    if name == "openai":
        from server.llms.openai import OpenAILLMService
        _require_key("OPENAI_API_KEY", cfg.OPENAI_API_KEY, name)
        return OpenAILLMService(api_key=cfg.OPENAI_API_KEY, model=cfg.OPENAI_MODEL)

    if name == "openrouter":
        from server.llms.openrouter import OpenRouterLLMService
        _require_key("OPENROUTER_API_KEY", cfg.OPENROUTER_API_KEY, name)
        return OpenRouterLLMService(
            api_key=cfg.OPENROUTER_API_KEY, model=cfg.OPENROUTER_MODEL
        )

    if name == "grok":
        from server.llms.grok import GrokLLMService
        _require_key("XAI_API_KEY", cfg.XAI_API_KEY, name)
        return GrokLLMService(api_key=cfg.XAI_API_KEY, model=cfg.GROK_MODEL)

    if name == "together":
        from server.llms.together import TogetherLLMService
        _require_key("TOGETHER_API_KEY", cfg.TOGETHER_API_KEY, name)
        return TogetherLLMService(
            api_key=cfg.TOGETHER_API_KEY, model=cfg.TOGETHER_MODEL
        )

    if name == "deepseek":
        from server.llms.deepseek import DeepSeekLLMService
        _require_key("DEEPSEEK_API_KEY", cfg.DEEPSEEK_API_KEY, name)
        return DeepSeekLLMService(
            api_key=cfg.DEEPSEEK_API_KEY, model=cfg.DEEPSEEK_MODEL
        )

    if name == "huggingface":
        from server.llms.huggingface import HuggingFaceLLMService
        _require_key("HF_API_KEY", cfg.HF_API_KEY, name)
        return HuggingFaceLLMService(api_key=cfg.HF_API_KEY, model=cfg.HF_MODEL)

    raise ValueError(
        f"Unknown provider {name!r}. "
        "Valid options: gemini, openai, openrouter, grok, together, deepseek, huggingface"
    )


def _require_key(env_var: str, value: str, provider: str) -> None:
    if not value:
        raise RuntimeError(
            f"Provider {provider!r} requires {env_var} to be set."
        )
