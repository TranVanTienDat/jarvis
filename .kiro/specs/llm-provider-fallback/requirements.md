# Requirements Document

## Introduction

Tính năng **LLM Provider Priority & Fallback Chain** bổ sung cơ chế tự động chuyển đổi giữa các nhà cung cấp LLM (Large Language Model) khi provider hiện tại gặp lỗi không thể phục hồi. Thay vì dừng hẳn khi một provider thất bại, hệ thống sẽ lần lượt thử các provider theo thứ tự ưu tiên đã cấu hình, đồng thời thông báo bằng giọng nói (text-to-speech) để người dùng biết quá trình chuyển đổi đang diễn ra.

Tính năng này được tích hợp vào `server/llms/factory.py` và `server/llms/base.py`, hoạt động trong môi trường Python async, sử dụng `LLMError` đã có sẵn để phân loại lỗi.

---

## Glossary

- **FallbackChain**: Thành phần trung tâm điều phối việc thử lần lượt các provider theo thứ tự ưu tiên.
- **Provider**: Một nhà cung cấp LLM cụ thể (Gemini, DeepSeek, Grok, OpenRouter, OpenAI, Together, HuggingFace), được biểu diễn bởi một `BaseLLMService`.
- **Provider_Order**: Danh sách thứ tự ưu tiên các provider, đọc từ biến môi trường `LLM_PROVIDER_ORDER`.
- **LLMError**: Exception hiện có trong `server/llms/base.py`, được raise bởi mọi provider khi gặp lỗi.
- **Fallback_Error**: Lỗi khiến hệ thống bỏ qua provider hiện tại và thử provider tiếp theo (403, 429, context length exceeded, timeout).
- **Retry_Error**: Lỗi tạm thời khiến hệ thống thử lại cùng provider trước khi quyết định fallback (5xx server error, connection reset).
- **TTS_Notifier**: Thành phần phát thông báo text-to-speech khi xảy ra fallback.
- **Error_Classifier**: Thành phần phân tích `LLMError` để xác định loại lỗi (Fallback_Error hay Retry_Error).
- **Max_Retry**: Số lần thử lại tối đa cho Retry_Error trước khi chuyển sang fallback, cấu hình qua `LLM_RETRY_MAX`.

---

## Requirements

### Requirement 1: Cấu hình thứ tự ưu tiên provider qua biến môi trường

**User Story:** Là một quản trị viên hệ thống, tôi muốn cấu hình thứ tự ưu tiên các LLM provider qua biến môi trường, để có thể thay đổi chiến lược fallback mà không cần sửa code.

#### Acceptance Criteria

1. WHEN **FallbackChain** được khởi tạo, THE **FallbackChain** SHALL đọc thứ tự provider từ biến môi trường `LLM_PROVIDER_ORDER` dưới dạng danh sách phân cách bởi dấu phẩy (ví dụ: `gemini,deepseek,grok,openrouter,openai,together,huggingface`), sau khi trim khoảng trắng ở đầu và cuối mỗi phần tử.
2. WHEN biến môi trường `LLM_PROVIDER_ORDER` không được thiết lập hoặc là chuỗi rỗng, THE **FallbackChain** SHALL sử dụng thứ tự mặc định: `gemini,deepseek,grok,openrouter,openai,together,huggingface`.
3. WHEN biến môi trường `LLM_PROVIDER_ORDER` chứa tên provider không thuộc tập hợp `{gemini, deepseek, grok, openrouter, openai, together, huggingface}`, THE **FallbackChain** SHALL bỏ qua provider đó và ghi log cảnh báo ở mức WARNING với tên provider không hợp lệ.
4. WHEN biến môi trường `LLM_PROVIDER_ORDER` chứa provider hợp lệ nhưng API key tương ứng là chuỗi rỗng hoặc không được thiết lập, THE **FallbackChain** SHALL bỏ qua provider đó khỏi danh sách hoạt động và ghi log cảnh báo ở mức WARNING.
5. WHEN tất cả provider trong `LLM_PROVIDER_ORDER` đều thiếu API key, THE **FallbackChain** SHALL không raise lỗi ngay lập tức mà giữ danh sách hoạt động rỗng; lỗi sẽ được xử lý theo Requirement 6, Criterion 3.

---

### Requirement 2: Phân loại lỗi để quyết định fallback hay retry

**User Story:** Là một hệ thống xử lý LLM, tôi muốn phân biệt lỗi cần fallback ngay với lỗi cần retry, để tránh lãng phí tài nguyên khi lỗi chỉ là tạm thời.

#### Acceptance Criteria

1. IF message của `LLMError` chứa chuỗi `"403"` hoặc bất kỳ từ khóa nào trong tập `{"forbidden", "invalid api key", "invalid_api_key", "authentication", "unauthorized", "permission denied"}` (so sánh không phân biệt hoa thường), THEN THE **Error_Classifier** SHALL phân loại lỗi đó thành `Fallback_Error`.
2. IF message của `LLMError` chứa chuỗi `"429"` hoặc bất kỳ từ khóa nào trong tập `{"rate limit", "rate_limit", "quota exceeded", "quota_exceeded", "too many requests", "resource exhausted"}` (so sánh không phân biệt hoa thường), THEN THE **Error_Classifier** SHALL phân loại lỗi đó thành `Fallback_Error`.
3. IF message của `LLMError` chứa bất kỳ từ khóa nào trong tập `{"context length", "context_length", "token limit", "token_limit", "maximum context", "max tokens", "max_tokens", "input too long", "content too long"}` (so sánh không phân biệt hoa thường), THEN THE **Error_Classifier** SHALL phân loại lỗi đó thành `Fallback_Error`.
4. IF `LLMError` được raise từ exception gốc là `asyncio.TimeoutError` hoặc `APITimeoutError`, hoặc message chứa từ khóa `"timeout"` (so sánh không phân biệt hoa thường), THEN THE **Error_Classifier** SHALL phân loại lỗi đó thành `Fallback_Error`.
5. IF message của `LLMError` chứa bất kỳ chuỗi nào trong tập `{"500", "502", "503", "504"}` hoặc bất kỳ từ khóa nào trong tập `{"internal server error", "bad gateway", "service unavailable", "gateway timeout", "server error"}` (so sánh không phân biệt hoa thường), THEN THE **Error_Classifier** SHALL phân loại lỗi đó thành `Retry_Error`.
6. IF message của `LLMError` chứa bất kỳ từ khóa nào trong tập `{"connection reset", "connection error", "connection refused", "connection aborted", "broken pipe", "network error"}` (so sánh không phân biệt hoa thường), THEN THE **Error_Classifier** SHALL phân loại lỗi đó thành `Retry_Error`.
7. IF một `LLMError` khớp đồng thời với pattern của cả `Fallback_Error` và `Retry_Error`, THEN THE **Error_Classifier** SHALL ưu tiên phân loại thành `Fallback_Error`.
8. IF `LLMError` không khớp với bất kỳ pattern nào trong các tiêu chí 1–6, THEN THE **Error_Classifier** SHALL phân loại lỗi đó thành `Fallback_Error` theo nguyên tắc fail-safe.

---

### Requirement 3: Cơ chế retry cho lỗi tạm thời

**User Story:** Là một hệ thống xử lý LLM, tôi muốn thử lại provider hiện tại khi gặp lỗi tạm thời, để tránh fallback không cần thiết khi server chỉ bị quá tải nhất thời.

#### Acceptance Criteria

1. WHEN **Error_Classifier** phân loại lỗi là `Retry_Error`, THE **FallbackChain** SHALL thử lại cùng provider tối đa `LLM_RETRY_MAX` lần (mặc định: 2 lần).
2. WHEN thực hiện retry lần thứ `attempt` (bắt đầu từ 1), THE **FallbackChain** SHALL chờ `retry_delay * (2 ^ attempt)` giây trước khi thử lại; với `LLM_RETRY_DELAY_S` mặc định là 1.0 giây, lần retry 1 chờ 2.0 giây, lần retry 2 chờ 4.0 giây.
3. IF số lần retry đã đạt bằng `LLM_RETRY_MAX`, THEN THE **FallbackChain** SHALL chuyển sang provider tiếp theo trong danh sách (fallback) thay vì thử lại.
4. WHEN biến môi trường `LLM_RETRY_MAX` được thiết lập, THE **FallbackChain** SHALL đọc giá trị đó; IF giá trị không phải số nguyên dương hoặc nhỏ hơn 0, THEN THE **FallbackChain** SHALL sử dụng giá trị mặc định 2 và ghi log cảnh báo ở mức WARNING.
5. WHEN biến môi trường `LLM_RETRY_DELAY_S` được thiết lập, THE **FallbackChain** SHALL đọc giá trị đó; IF giá trị không phải số thực dương hoặc nhỏ hơn hoặc bằng 0, THEN THE **FallbackChain** SHALL sử dụng giá trị mặc định 1.0 giây và ghi log cảnh báo ở mức WARNING.

---

### Requirement 4: Cơ chế fallback tự động sang provider tiếp theo

**User Story:** Là một người dùng cuối, tôi muốn hệ thống tự động chuyển sang provider khác khi provider hiện tại không khả dụng, để cuộc hội thoại không bị gián đoạn.

#### Acceptance Criteria

1. WHEN **Error_Classifier** phân loại lỗi là `Fallback_Error`, THE **FallbackChain** SHALL chuyển sang provider tiếp theo trong `Provider_Order` mà không thực hiện bất kỳ lần retry nào với provider hiện tại.
2. WHEN fallback xảy ra, THE **FallbackChain** SHALL ghi log ở mức WARNING với thông tin: tên provider thất bại, loại lỗi được phân loại, và tên provider tiếp theo được thử.
3. WHEN fallback xảy ra, THE **FallbackChain** SHALL truyền sang provider tiếp theo danh sách `messages` với nội dung và thứ tự giống hệt lần gọi ban đầu, cùng với giá trị `system_context` không thay đổi.
4. WHEN provider tiếp theo trong danh sách cũng thất bại, THE **FallbackChain** SHALL tiếp tục thử provider kế tiếp theo thứ tự cho đến hết danh sách.
5. WHILE streaming đang diễn ra (đã yield ít nhất một chunk) và provider gặp lỗi, IF **Error_Classifier** phân loại lỗi là `Fallback_Error`, THEN THE **FallbackChain** SHALL hủy stream hiện tại và bắt đầu lại từ đầu với provider tiếp theo, không truyền lại các chunk đã yield trước đó.
6. WHEN fallback xảy ra sau khi đã yield ít nhất một chunk, THE **FallbackChain** SHALL không phát lại các token đã được yield trước khi lỗi xảy ra; provider tiếp theo sẽ bắt đầu stream từ đầu với toàn bộ `messages` gốc.

---

### Requirement 5: Thông báo text-to-speech khi fallback xảy ra

**User Story:** Là một người dùng cuối, tôi muốn nghe thông báo bằng giọng nói khi hệ thống chuyển đổi provider, để tôi hiểu tại sao có độ trễ và hệ thống đang làm gì.

#### Acceptance Criteria

1. WHEN **FallbackChain** quyết định chuyển sang provider tiếp theo, THE **TTS_Notifier** SHALL phát thông báo bằng tiếng Việt theo mẫu: `"[Tên provider] đã [lý do lỗi], tôi đang chuyển sang sử dụng [tên provider tiếp theo]"`.
2. THE **TTS_Notifier** SHALL sử dụng tên hiển thị thân thiện cho từng provider: `gemini` → "Gemini", `deepseek` → "DeepSeek", `grok` → "Grok", `openrouter` → "OpenRouter", `openai` → "OpenAI", `together` → "Together", `huggingface` → "HuggingFace".
3. THE **TTS_Notifier** SHALL ánh xạ loại lỗi sang lý do thân thiện như sau:
   - Lỗi 403 / authentication: "không có quyền truy cập"
   - Lỗi 429 / rate limit / quota: "đã hết quota"
   - Context length / token limit: "đã hết token"
   - Timeout: "không phản hồi"
   - Lỗi không thuộc các loại trên: "gặp sự cố"
4. WHEN tất cả provider đều thất bại, THE **TTS_Notifier** SHALL phát thông báo: `"Tất cả các dịch vụ AI đều không khả dụng, vui lòng thử lại sau"`.
5. THE **TTS_Notifier** SHALL phát thông báo bất đồng bộ (non-blocking) bằng cách tạo asyncio task riêng biệt; IF TTS gặp lỗi trong quá trình phát, THE **TTS_Notifier** SHALL ghi log ở mức WARNING và tiếp tục quá trình fallback mà không raise exception; thời gian chờ tối đa cho mỗi thông báo TTS là 5 giây.
6. WHEN một thông báo TTS đang phát và một fallback mới xảy ra, THE **TTS_Notifier** SHALL hủy thông báo đang phát và bắt đầu thông báo mới ngay lập tức.

---

### Requirement 6: Xử lý khi tất cả provider đều thất bại

**User Story:** Là một người dùng cuối, tôi muốn nhận được thông báo lỗi rõ ràng khi không có provider nào hoạt động được, để tôi biết cần liên hệ hỗ trợ hoặc thử lại sau.

#### Acceptance Criteria

1. WHEN tất cả provider trong danh sách hoạt động đều thất bại, THE **FallbackChain** SHALL raise `LLMError` với message tổng hợp theo định dạng: `"Tất cả {n} provider đều thất bại: [{provider_1}: {error_type_1} ({status_code_1}), {provider_2}: {error_type_2}, ...]"`, trong đó `status_code` được bao gồm khi có, và `n` là tổng số provider đã thử.
2. WHEN tất cả provider thất bại, THE **FallbackChain** SHALL bao gồm trong `LLMError` cuối cùng: danh sách provider đã thử theo thứ tự, loại lỗi (`Fallback_Error` hoặc `Retry_Error`) của từng provider, HTTP status code nếu có, và tổng số lần thử bao gồm cả retry (ví dụ: provider A thất bại sau 3 lần thử = 1 lần gốc + 2 retry).
3. IF danh sách provider hoạt động rỗng khi `stream()` được gọi (do tất cả thiếu API key theo Requirement 1, Criterion 5), THEN THE **FallbackChain** SHALL raise `LLMError` với message `"Không có provider nào được cấu hình: danh sách hoạt động rỗng"` mà không thực hiện bất kỳ lần thử nào.

---

### Requirement 7: Tích hợp với factory và interface hiện có

**User Story:** Là một developer, tôi muốn tính năng fallback được tích hợp minh bạch vào codebase hiện tại, để không cần thay đổi code ở các tầng khác của ứng dụng.

#### Acceptance Criteria

1. THE **FallbackChain** SHALL implement `BaseLLMService` với method `async def stream(self, messages: list[ConversationMessage], system_context: str = "") -> AsyncIterator[str]` là async generator, tương thích với signature hiện có trong `server/llms/base.py`.
2. THE **FallbackChain** SHALL implement `async def close(self) -> None` để gọi `close()` trên tất cả provider trong danh sách hoạt động; IF một provider raise exception trong `close()`, THE **FallbackChain** SHALL ghi log ở mức WARNING và tiếp tục đóng các provider còn lại.
3. WHEN biến môi trường `LLM_PROVIDER_ORDER` được thiết lập và không rỗng, THE `create_llm_service()` factory function SHALL trả về instance `FallbackChain` thay vì single provider, bất kể `LLM_PROVIDER` có được thiết lập hay không.
4. WHEN `LLM_PROVIDER_ORDER` không được thiết lập hoặc rỗng và `LLM_PROVIDER` được thiết lập, THE `create_llm_service()` factory function SHALL trả về single provider instance tương ứng với `LLM_PROVIDER`, giống hệt hành vi hiện tại trước khi có tính năng này.
5. WHEN cả `LLM_PROVIDER_ORDER` và `LLM_PROVIDER` đều không được thiết lập, THE `create_llm_service()` factory function SHALL sử dụng giá trị mặc định `LLM_PROVIDER=gemini` theo hành vi hiện tại của `server/config.py`.
6. WHEN **FallbackChain** gọi `stream()` trên một provider, THE **FallbackChain** SHALL truyền `system_context` với giá trị không thay đổi so với giá trị nhận được từ caller ban đầu.

---

### Requirement 8: Logging và observability

**User Story:** Là một developer vận hành hệ thống, tôi muốn có đủ thông tin log để debug và theo dõi hành vi fallback, để có thể phát hiện và xử lý sự cố kịp thời.

#### Acceptance Criteria

1. WHEN một provider thất bại và fallback xảy ra, THE **FallbackChain** SHALL ghi log ở mức WARNING với thông tin: tên provider thất bại, loại lỗi được phân loại (`Fallback_Error` hoặc `Retry_Error`), HTTP status code nếu có trong message lỗi, và tên provider tiếp theo được thử.
2. WHEN retry xảy ra, THE **FallbackChain** SHALL ghi log ở mức DEBUG với thông tin: tên provider, số lần retry hiện tại (ví dụ: `1/2`), và thời gian chờ tính bằng giây với 2 chữ số thập phân (ví dụ: `2.00s`).
3. WHEN tất cả provider thất bại, THE **FallbackChain** SHALL ghi log ở mức ERROR với thông tin: tên từng provider đã thử theo thứ tự, loại lỗi tương ứng, HTTP status code nếu có, và tổng số lần thử bao gồm retry.
4. WHEN một provider thành công sau khi ít nhất một fallback đã xảy ra trong cùng request, THE **FallbackChain** SHALL ghi log ở mức INFO với tên provider đang được sử dụng thành công.
5. THE **FallbackChain** SHALL sử dụng Python standard `logging` module với logger name `server.llms.fallback`.
