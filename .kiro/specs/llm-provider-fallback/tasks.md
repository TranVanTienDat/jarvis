# Implementation Plan

## Overview

Implement LLM Provider Priority & Fallback Chain: tự động chuyển đổi provider khi gặp lỗi, retry cho lỗi tạm thời, thông báo TTS khi fallback.

## Tasks

- [ ] 1. Update config.py — add fallback chain env vars
  - Add `LLM_PROVIDER_ORDER: str` with default `""`
  - Add `LLM_RETRY_MAX: int` with default `2`, validation (non-integer or < 0 → default + WARNING log)
  - Add `LLM_RETRY_DELAY_S: float` with default `1.0`, validation (non-numeric or <= 0 → default + WARNING log)
  - Update comments in config.py to describe the 3 new variables
  - **Files:** `server/config.py`

- [ ] 2. Create ErrorClassifier (`server/llms/fallback/classifier.py`)
  - Create `server/llms/fallback/` directory and `__init__.py`
  - Create `ErrorKind` enum with `FALLBACK` and `RETRY` values
  - Implement `ErrorClassifier.classify(error: LLMError) -> ErrorKind` with full keyword pattern matching (403/forbidden/auth → FALLBACK, 429/rate-limit/quota → FALLBACK, context-length/token-limit → FALLBACK, timeout → FALLBACK, 5xx/server-error → RETRY, connection-reset/error → RETRY, conflict → FALLBACK wins, default → FALLBACK)
  - Implement `ErrorClassifier.get_tts_reason(error: LLMError) -> str` returning friendly Vietnamese reason string
  - Export `ErrorClassifier`, `ErrorKind` from `server/llms/fallback/__init__.py`
  - **Files:** `server/llms/fallback/__init__.py`, `server/llms/fallback/classifier.py`

- [ ] 3. Create FallbackNotifier (`server/llms/fallback/notifier.py`)
  - Define `PROVIDER_DISPLAY_NAMES` dict mapping provider keys to friendly display names
  - Implement `FallbackNotifier.__init__(tts_service: TTSService)`
  - Implement `notify_fallback(from_provider, to_provider, reason, websocket)`: build Vietnamese message, create non-blocking asyncio.Task, cancel previous task if running, 5s timeout, silent fail on TTS error
  - Implement `notify_all_failed(websocket)`: same non-blocking pattern
  - Export `FallbackNotifier` from `server/llms/fallback/__init__.py`
  - **Files:** `server/llms/fallback/notifier.py`, `server/llms/fallback/__init__.py`

- [ ] 4. Create FallbackChain (`server/llms/fallback/chain.py`)
  - Depends on: tasks 2, 3
  - Implement `FallbackChain.__init__(providers, notifier, max_retry, retry_delay_s)`
  - Implement `set_websocket(websocket)` for injecting websocket for TTS notifications
  - Implement `stream(messages, system_context)`: loop providers, exponential backoff retry for RETRY errors (`delay * 2^attempt`, attempt starts at 1), immediate fallback for FALLBACK errors, call notifier on fallback, log WARNING on fallback / DEBUG on retry / INFO on success after fallback, raise LLMError if providers list empty, raise LLMError with summary if all fail
  - Implement `close()`: call close() on all providers, log WARNING on individual close errors and continue
  - Implement `_build_summary_message(failures)` helper for formatted error summary
  - Export `FallbackChain` from `server/llms/fallback/__init__.py`
  - **Files:** `server/llms/fallback/chain.py`, `server/llms/fallback/__init__.py`

- [ ] 5. Update factory.py
  - Depends on: tasks 1, 4
  - Extract existing provider creation logic into `_create_single_provider(provider_name: str) -> BaseLLMService`
  - Add `_create_fallback_chain() -> FallbackChain`: parse LLM_PROVIDER_ORDER, skip invalid/missing-key providers with WARNING log, instantiate TTSService + FallbackNotifier + FallbackChain
  - Update `create_llm_service()`: if `cfg.LLM_PROVIDER_ORDER` non-empty → return FallbackChain, else → return single provider (backward compatible)
  - Update docstring to document LLM_PROVIDER_ORDER and new env vars
  - **Files:** `server/llms/factory.py`

- [ ] 6. Update Orchestrator to inject websocket into FallbackChain
  - Depends on: task 4
  - In `Orchestrator._pipeline()`, before calling `self.llm_service.stream()`, check `hasattr(self.llm_service, "set_websocket")` and call `set_websocket(websocket)` if present
  - Use duck typing only — do not change BaseLLMService interface
  - **Files:** `server/orchestrator/core.py`

- [ ] 7. Update .env.example
  - Depends on: task 1
  - Add new section with `LLM_PROVIDER_ORDER`, `LLM_RETRY_MAX`, `LLM_RETRY_DELAY_S` with explanatory comments
  - Add full example config with all 7 providers in default priority order
  - **Files:** `.env.example`

## Task Dependency Graph

```
1 (config)
├── 2 (ErrorClassifier)   [parallel with 3]
├── 3 (FallbackNotifier)  [parallel with 2]
│   └── 4 (FallbackChain) [needs 2 + 3]
│       ├── 5 (factory)   [needs 1 + 4, parallel with 6, 7]
│       ├── 6 (Orchestrator) [needs 4, parallel with 5, 7]
│       └── 7 (.env.example) [needs 1, parallel with 5, 6]
```

## Notes

- Tasks 2 and 3 can run in parallel after task 1 completes
- Tasks 5, 6, 7 can run in parallel after task 4 completes
- Backward compatible: if `LLM_PROVIDER_ORDER` is not set, behavior is identical to current
- The `set_websocket()` pattern uses duck typing to avoid changing BaseLLMService interface
