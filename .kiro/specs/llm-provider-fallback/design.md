# Design Document — LLM Provider Priority & Fallback Chain

## Overview

Tính năng này bổ sung `FallbackChain` — một `BaseLLMService` wrapper điều phối việc thử lần lượt các provider theo thứ tự ưu tiên. Khi một provider thất bại, `FallbackChain` phân loại lỗi, quyết định retry hay fallback, phát thông báo TTS, rồi thử provider tiếp theo. Toàn bộ logic được đóng gói trong `server/llms/fallback/` và tích hợp vào `factory.py` — các tầng khác (Orchestrator, WebSocket handler) không cần thay đổi.

---

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Orchestrator                         │
│              llm_service.stream(messages)                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ BaseLLMService interface
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      FallbackChain                          │
│                                                             │
│  providers: [GeminiLLMService, DeepSeekLLMService, ...]     │
│                                                             │
│  ┌──────────────────┐   ┌──────────────────┐                │
│  │  ErrorClassifier │   │   TTS_Notifier   │                │
│  │                  │   │  (non-blocking)  │                │
│  │ classify(err) →  │   │  notify(from,    │                │
│  │ Fallback_Error   │   │   to, reason)    │                │
│  │ Retry_Error      │   └──────────────────┘                │
│  └──────────────────┘                                       │
│                                                             │
│  Loop: for provider in providers:                           │
│    retry_count = 0                                          │
│    while retry_count <= LLM_RETRY_MAX:                      │
│      try: yield from provider.stream()                      │
│      except LLMError as e:                                  │
│        if Retry_Error and retry_count < max: retry          │
│        else: notify TTS → next provider                     │
└─────────────────────────────────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
   GeminiLLMService  DeepSeekLLMService  GrokLLMService  ...
```

### File Structure

```
server/llms/
├── base.py                    # BaseLLMService, LLMError (hiện có)
├── factory.py                 # create_llm_service() — cập nhật
├── fallback/
│   ├── __init__.py            # export FallbackChain
│   ├── chain.py               # FallbackChain — logic chính
│   ├── classifier.py          # ErrorClassifier
│   └── notifier.py            # FallbackNotifier (TTS wrapper)
├── gemini/                    # không thay đổi
├── openai/                    # không thay đổi
├── deepseek/                  # không thay đổi
├── grok/                      # không thay đổi
├── openrouter/                # không thay đổi
├── together/                  # không thay đổi
└── huggingface/               # không thay đổi
```

---

## Components

### 1. `ErrorClassifier` (`server/llms/fallback/classifier.py`)

Phân loại `LLMError` thành `ErrorKind` enum.

```python
from enum import Enum

class ErrorKind(Enum):
    FALLBACK = "fallback"   # bỏ qua provider, thử tiếp
    RETRY    = "retry"      # thử lại cùng provider

class ErrorClassifier:
    def classify(self, error: LLMError) -> ErrorKind: ...
    def get_tts_reason(self, error: LLMError) -> str: ...
```

**Bảng phân loại:**

| Pattern (case-insensitive)                                                                                                                                              | ErrorKind | TTS reason                |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | ------------------------- |
| `"403"`, `"forbidden"`, `"invalid api key"`, `"invalid_api_key"`, `"authentication"`, `"unauthorized"`, `"permission denied"`                                           | FALLBACK  | "không có quyền truy cập" |
| `"429"`, `"rate limit"`, `"rate_limit"`, `"quota exceeded"`, `"quota_exceeded"`, `"too many requests"`, `"resource exhausted"`                                          | FALLBACK  | "đã hết quota"            |
| `"context length"`, `"context_length"`, `"token limit"`, `"token_limit"`, `"maximum context"`, `"max tokens"`, `"max_tokens"`, `"input too long"`, `"content too long"` | FALLBACK  | "đã hết token"            |
| `"timeout"`, `asyncio.TimeoutError`, `APITimeoutError`                                                                                                                  | FALLBACK  | "không phản hồi"          |
| `"500"`, `"502"`, `"503"`, `"504"`, `"internal server error"`, `"bad gateway"`, `"service unavailable"`, `"gateway timeout"`, `"server error"`                          | RETRY     | —                         |
| `"connection reset"`, `"connection error"`, `"connection refused"`, `"connection aborted"`, `"broken pipe"`, `"network error"`                                          | RETRY     | —                         |
| Không khớp                                                                                                                                                              | FALLBACK  | "gặp sự cố"               |

**Ưu tiên conflict:** Nếu khớp cả FALLBACK và RETRY → FALLBACK thắng.

---

### 2. `FallbackNotifier` (`server/llms/fallback/notifier.py`)

Wrapper mỏng quanh `TTSService` để phát thông báo non-blocking.

```python
class FallbackNotifier:
    def __init__(self, tts_service: TTSService) -> None: ...

    async def notify_fallback(
        self,
        from_provider: str,   # e.g. "gemini"
        to_provider: str,     # e.g. "deepseek"
        reason: str,          # e.g. "đã hết token"
        websocket: WebSocket,
    ) -> None: ...
    # Tạo asyncio.Task riêng, timeout 5s, silent fail

    async def notify_all_failed(self, websocket: WebSocket) -> None: ...
    # "Tất cả các dịch vụ AI đều không khả dụng, vui lòng thử lại sau"
```

**Tên hiển thị provider:**

```python
PROVIDER_DISPLAY_NAMES = {
    "gemini":      "Gemini",
    "deepseek":    "DeepSeek",
    "grok":        "Grok",
    "openrouter":  "OpenRouter",
    "openai":      "OpenAI",
    "together":    "Together",
    "huggingface": "HuggingFace",
}
```

**Thông báo mẫu:**

- Fallback: `"Gemini đã hết token, tôi đang chuyển sang sử dụng DeepSeek"`
- All failed: `"Tất cả các dịch vụ AI đều không khả dụng, vui lòng thử lại sau"`

**Non-blocking:** Dùng `asyncio.create_task()`. Nếu task đang chạy và có fallback mới → cancel task cũ, tạo task mới. Nếu TTS lỗi → log WARNING, không raise.

---

### 3. `FallbackChain` (`server/llms/fallback/chain.py`)

Core logic. Implement `BaseLLMService`.

```python
class FallbackChain(BaseLLMService):
    provider_name = "fallback_chain"

    def __init__(
        self,
        providers: list[BaseLLMService],
        notifier: FallbackNotifier,
        max_retry: int = 2,
        retry_delay_s: float = 1.0,
    ) -> None: ...

    async def stream(
        self,
        messages: list[ConversationMessage],
        system_context: str = "",
        websocket: WebSocket | None = None,
    ) -> AsyncIterator[str]: ...

    async def close(self) -> None: ...
```

**Stream algorithm:**

```
failures = []
for i, provider in enumerate(providers):
    retry_count = 0
    while True:
        try:
            async for token in provider.stream(messages, system_context):
                yield token
            # success
            if failures:
                log INFO "provider.name succeeded after fallbacks"
            return
        except LLMError as exc:
            kind = classifier.classify(exc)
            if kind == RETRY and retry_count < max_retry:
                retry_count += 1
                delay = retry_delay_s * (2 ** retry_count)
                log DEBUG f"retry {retry_count}/{max_retry}, wait {delay:.2f}s"
                await asyncio.sleep(delay)
                continue
            # fallback
            failures.append((provider.provider_name, exc))
            next_provider = providers[i+1] if i+1 < len(providers) else None
            log WARNING f"{provider.name} failed → {next_provider or 'none'}"
            if next_provider and websocket:
                reason = classifier.get_tts_reason(exc)
                await notifier.notify_fallback(
                    provider.provider_name,
                    next_provider.provider_name,
                    reason,
                    websocket,
                )
            break

# All failed
if websocket:
    await notifier.notify_all_failed(websocket)
log ERROR "all providers failed: ..."
raise LLMError(build_summary_message(failures))
```

**Lưu ý về mid-stream fallback:** Nếu provider raise `LLMError` sau khi đã yield một số token, `FallbackChain` sẽ bắt đầu lại từ đầu với provider tiếp theo. Các token đã yield không được phát lại — caller (Orchestrator/TTS) sẽ nhận stream mới từ đầu. Đây là trade-off chấp nhận được vì TTS đã buffer theo câu.

---

### 4. Cập nhật `factory.py`

```python
def create_llm_service() -> BaseLLMService:
    # Nếu LLM_PROVIDER_ORDER được set → trả về FallbackChain
    if cfg.LLM_PROVIDER_ORDER:
        return _create_fallback_chain()
    # Ngược lại → hành vi cũ
    return _create_single_provider(cfg.LLM_PROVIDER)

def _create_fallback_chain() -> FallbackChain:
    order = [p.strip() for p in cfg.LLM_PROVIDER_ORDER.split(",")]
    providers = []
    for name in order:
        try:
            svc = _create_single_provider(name)
            providers.append(svc)
        except (ValueError, RuntimeError) as e:
            logger.warning("Skipping provider %r: %s", name, e)
    tts = TTSService()
    notifier = FallbackNotifier(tts)
    return FallbackChain(
        providers=providers,
        notifier=notifier,
        max_retry=cfg.LLM_RETRY_MAX,
        retry_delay_s=cfg.LLM_RETRY_DELAY_S,
    )
```

---

### 5. Cập nhật `config.py`

Thêm các biến mới:

```python
# ─── LLM — Fallback chain ─────────────────────────────────────────────────────
# Comma-separated provider order. When set, enables FallbackChain.
# Example: "gemini,deepseek,grok,openrouter,openai,together,huggingface"
LLM_PROVIDER_ORDER: str = os.environ.get("LLM_PROVIDER_ORDER", "")

# Max retries per provider on transient errors (5xx, connection reset)
LLM_RETRY_MAX: int = int(os.environ.get("LLM_RETRY_MAX", "2"))

# Base delay in seconds for exponential backoff (delay * 2^attempt)
LLM_RETRY_DELAY_S: float = float(os.environ.get("LLM_RETRY_DELAY_S", "1.0"))
```

---

### 6. Cập nhật `stream()` signature — truyền `websocket`

`FallbackChain.stream()` cần `websocket` để `FallbackNotifier` gửi audio TTS. Tuy nhiên `BaseLLMService.stream()` hiện không có tham số này.

**Giải pháp:** Inject `websocket` vào `FallbackChain` tại thời điểm gọi qua một method riêng, không thay đổi `BaseLLMService` interface:

```python
class FallbackChain(BaseLLMService):
    def set_websocket(self, websocket: WebSocket) -> None:
        """Inject websocket for TTS notifications. Call before stream()."""
        self._websocket = websocket

    async def stream(
        self,
        messages: list[ConversationMessage],
        system_context: str = "",
    ) -> AsyncIterator[str]:
        # sử dụng self._websocket (có thể None nếu chưa set)
        ...
```

Orchestrator gọi:

```python
if hasattr(self.llm_service, "set_websocket"):
    self.llm_service.set_websocket(websocket)
async for token in self.llm_service.stream(messages):
    ...
```

---

## Data Flow

### Happy path (Gemini thành công)

```
Orchestrator.stream(messages)
  → FallbackChain.stream(messages)
    → GeminiLLMService.stream(messages)
      → yield tokens...
    ← tokens streamed successfully
  ← tokens forwarded to TTS
```

### Fallback path (Gemini 429 → DeepSeek)

```
Orchestrator.stream(messages)
  → FallbackChain.stream(messages)
    → GeminiLLMService.stream(messages)
      ← raise LLMError("429 rate limit")
    → ErrorClassifier.classify() → FALLBACK, reason="đã hết quota"
    → FallbackNotifier.notify_fallback("gemini", "deepseek", "đã hết quota")
      → asyncio.create_task(tts.synthesize("Gemini đã hết quota..."))  [non-blocking]
    → log WARNING "gemini failed (429) → deepseek"
    → DeepSeekLLMService.stream(messages)
      → yield tokens...
    ← tokens streamed successfully
    → log INFO "deepseek succeeded after 1 fallback"
  ← tokens forwarded to TTS
```

### Retry path (Gemini 503 → retry → success)

```
FallbackChain.stream(messages)
  → GeminiLLMService.stream(messages)
    ← raise LLMError("503 service unavailable")
  → ErrorClassifier.classify() → RETRY
  → log DEBUG "retry 1/2, wait 2.00s"
  → asyncio.sleep(2.0)
  → GeminiLLMService.stream(messages)  [retry]
    → yield tokens...
  ← success, no fallback needed
```

### All failed path

```
FallbackChain.stream(messages)
  → [all providers fail]
  → FallbackNotifier.notify_all_failed(websocket)
  → log ERROR "all 7 providers failed: ..."
  → raise LLMError("Tất cả 7 provider đều thất bại: [gemini: FALLBACK (429), ...]")
← Orchestrator catches LLMError → sends ErrorMsg to client
```

---

## Environment Variables Reference

| Variable             | Default         | Mô tả                                                                                        |
| -------------------- | --------------- | -------------------------------------------------------------------------------------------- |
| `LLM_PROVIDER_ORDER` | `""` (disabled) | Danh sách provider theo thứ tự ưu tiên, phân cách bởi dấu phẩy. Khi set → bật FallbackChain. |
| `LLM_RETRY_MAX`      | `2`             | Số lần retry tối đa cho lỗi tạm thời (5xx, connection reset).                                |
| `LLM_RETRY_DELAY_S`  | `1.0`           | Delay cơ sở (giây) cho exponential backoff: `delay * 2^attempt`.                             |

**Ví dụ `.env`:**

```env
LLM_PROVIDER_ORDER=gemini,deepseek,grok,openrouter,openai,together,huggingface
LLM_RETRY_MAX=2
LLM_RETRY_DELAY_S=1.0

# API keys cho từng provider
GEMINI_API_KEY=...
DEEPSEEK_API_KEY=...
XAI_API_KEY=...
OPENROUTER_API_KEY=...
OPENAI_API_KEY=...
TOGETHER_API_KEY=...
HF_API_KEY=...
```

---

## Error Message Format

Khi tất cả provider thất bại, `LLMError` message có dạng:

```
Tất cả 3 provider đều thất bại:
  - gemini: FALLBACK (429 rate limit) [1 lần thử]
  - deepseek: FALLBACK (timeout) [1 lần thử]
  - grok: RETRY (503 service unavailable) [3 lần thử]
```

---

## Backward Compatibility

| Scenario                                          | Hành vi                                                |
| ------------------------------------------------- | ------------------------------------------------------ |
| `LLM_PROVIDER_ORDER` không set                    | `create_llm_service()` trả về single provider như cũ   |
| `LLM_PROVIDER_ORDER` set, `LLM_PROVIDER` cũng set | `FallbackChain` được dùng, `LLM_PROVIDER` bị bỏ qua    |
| `LLM_PROVIDER_ORDER` set nhưng chỉ 1 provider     | `FallbackChain` với 1 provider (hoạt động bình thường) |
| Provider trong order thiếu API key                | Bị bỏ qua, log WARNING                                 |

---

## Testing Strategy

### Unit tests

- `ErrorClassifier`: test từng pattern keyword, test conflict resolution, test default fallback
- `FallbackChain`: mock providers, test retry count, test exponential backoff timing, test mid-stream fallback, test all-failed message format
- `FallbackNotifier`: mock TTSService, test non-blocking behavior, test task cancellation

### Integration tests

- `create_llm_service()` với `LLM_PROVIDER_ORDER` set → trả về `FallbackChain`
- `create_llm_service()` không có `LLM_PROVIDER_ORDER` → trả về single provider
- End-to-end: mock provider raise 429 → verify fallback to next provider
