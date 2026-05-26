# Requirements Document

## Introduction

Hệ thống Voice Chatbot IoT thời gian thực là một nền tảng hội thoại bằng giọng nói cho phép người dùng điều khiển các thiết bị nhà thông minh thông qua ngôn ngữ tự nhiên tiếng Việt. Hệ thống gồm hai thành phần chính: **Client** chạy trên Raspberry Pi (xử lý âm thanh cục bộ, phát hiện wake word, STT local, phát loa) và **Server** chạy trên FastAPI (điều phối AI, LLM streaming, TTS streaming, điều khiển IoT qua MQTT). Hai thành phần giao tiếp qua WebSocket song công (full-duplex) với độ trễ đầu cuối mục tiêu dưới 500ms.

---

## Glossary

- **Client**: Thiết bị edge (Raspberry Pi) chạy pipeline xử lý âm thanh cục bộ.
- **Server**: Máy chủ FastAPI đóng vai trò điều phối trung tâm (Orchestrator).
- **VAD (Voice Activity Detection)**: Bộ phát hiện giọng nói sử dụng thư viện `webrtcvad`.
- **Wake_Word_Detector**: Module phát hiện từ khóa kích hoạt "Hey AI" sử dụng `pvporcupine`.
- **STT_Engine**: Module chuyển đổi giọng nói thành văn bản cục bộ sử dụng `moonshine-tiny-vi`.
- **WebSocket_Client**: Module kết nối WebSocket phía Client.
- **WebSocket_Server**: Module WebSocket endpoint phía Server (FastAPI).
- **Orchestrator**: Bộ điều phối trung tâm trên Server, tích hợp các module AI và ra quyết định.
- **Context_Manager**: Module quản lý lịch sử hội thoại ngắn hạn trên Redis.
- **Intent_Classifier**: Module phân loại ý định người dùng sử dụng Gemini Function Calling.
- **Policy_Engine**: Module thực thi quy tắc nghiệp vụ và điều phối hành động.
- **State_Manager**: Module quản lý máy trạng thái (IDLE → LISTENING → PROCESSING → SPEAKING → ERROR).
- **Tool_Manager**: Module thực thi các công cụ bên ngoài (MQTT, API thời tiết...).
- **LLM**: Mô hình ngôn ngữ lớn Gemini 1.5 Flash, sinh phản hồi dạng streaming.
- **TTS_Engine**: Module chuyển đổi văn bản thành giọng nói sử dụng Edge-TTS streaming.
- **MQTT_Manager**: Module giao tiếp MQTT bất đồng bộ với thiết bị IoT qua `paho-mqtt`.
- **ESP32**: Vi điều khiển phần cứng đầu cuối kết nối qua MQTT Broker (Mosquitto).
- **Barge_In**: Tính năng ngắt lời — người dùng nói chen ngang khi loa đang phát.
- **Audio_Player**: Module phát âm thanh TTS qua loa trên Client.
- **Partial_Transcript**: Văn bản nhận dạng tạm thời từng token từ STT_Engine.
- **Final_Transcript**: Văn bản nhận dạng đầy đủ sau khi VAD phát hiện khoảng lặng.
- **Session**: Phiên làm việc của một kết nối WebSocket, được định danh bằng `session_id`.

---

## Requirements

### Yêu Cầu 1: Thu Âm và Phát Hiện Giọng Nói (Audio Capture & VAD)

**User Story:** Là một người dùng, tôi muốn hệ thống tự động phát hiện khi tôi bắt đầu và kết thúc nói, để hệ thống chỉ xử lý âm thanh khi có giọng nói thực sự.

#### Tiêu Chí Chấp Nhận

1. THE Client SHALL thu âm liên tục từ microphone với tần số lấy mẫu 16kHz, độ sâu bit 16-bit, kênh đơn (Mono) sử dụng thư viện `sounddevice`.
2. THE VAD SHALL xử lý từng frame âm thanh có độ dài 30ms để phân loại là giọng nói hoặc khoảng lặng.
3. WHEN VAD phát hiện khoảng lặng liên tục vượt quá 500ms (tương đương 17 frame x 30ms), THE Client SHALL xác định người dùng đã kết thúc câu nói và kích hoạt gửi Final_Transcript lên Server.
4. IF VAD không nhận được tín hiệu âm thanh hợp lệ từ thiết bị microphone, THEN THE Client SHALL ghi nhận lỗi và chuyển sang trạng thái ERROR.

---

### Yêu Cầu 2: Phát Hiện Wake Word

**User Story:** Là một người dùng, tôi muốn hệ thống chỉ kích hoạt khi tôi nói "Hey AI", để tránh xử lý âm thanh nền không cần thiết và tiết kiệm tài nguyên.

#### Tiêu Chí Chấp Nhận

1. WHILE Client đang ở trạng thái IDLE, THE Wake_Word_Detector SHALL liên tục phân tích luồng âm thanh cục bộ để phát hiện từ khóa "Hey AI" sử dụng `pvporcupine` mà không truyền dữ liệu lên Server.
2. WHEN Wake_Word_Detector phát hiện từ khóa "Hey AI", THE Client SHALL chuyển sang trạng thái LISTENING và bắt đầu pipeline xử lý STT.
3. WHILE Client đang ở trạng thái IDLE, THE Client SHALL không truyền bất kỳ dữ liệu âm thanh nào lên Server.
4. IF Wake_Word_Detector không khởi tạo được do thiếu license key hoặc lỗi phần cứng, THEN THE Client SHALL ghi nhận lỗi khởi tạo và dừng pipeline.

---

### Yêu Cầu 3: Nhận Dạng Giọng Nói Cục Bộ (Local STT Streaming)

**User Story:** Là một người dùng, tôi muốn câu nói của mình được chuyển thành văn bản ngay trên thiết bị và gửi lên Server theo từng token, để giảm độ trễ và bảo vệ quyền riêng tư.

#### Tiêu Chí Chấp Nhận

1. WHEN Client chuyển sang trạng thái LISTENING, THE STT_Engine SHALL nhận dạng giọng nói tiếng Việt sử dụng mô hình `UsefulSensors/moonshine-tiny-vi` thông qua `MoonshineForConditionalGeneration`.
2. WHEN STT_Engine sinh ra từng token mới, THE STT_Engine SHALL sử dụng `TextIteratorStreamer` để phát ra từng token ngay lập tức mà không chờ hoàn thành toàn bộ câu.
3. WHEN STT_Engine sinh ra một token mới, THE WebSocket_Client SHALL gửi bản tin JSON `{"event": "partial_transcript", "token": "<token>"}` lên Server ngay lập tức.
4. WHEN VAD xác định kết thúc câu nói, THE WebSocket_Client SHALL gửi bản tin JSON `{"event": "final_transcript", "text": "<full_text>"}` lên Server.
5. IF STT_Engine gặp lỗi trong quá trình nhận dạng, THEN THE Client SHALL gửi bản tin JSON `{"event": "stt_error", "message": "<error_detail>"}` lên Server và chuyển về trạng thái IDLE.

---

### Yêu Cầu 4: Kết Nối WebSocket và Giao Thức Truyền Tin

**User Story:** Là một nhà phát triển, tôi muốn Client và Server giao tiếp qua WebSocket với định dạng JSON chuẩn hóa, để dễ dàng mở rộng và gỡ lỗi hệ thống.

#### Tiêu Chí Chấp Nhận

1. THE WebSocket_Client SHALL duy trì một kết nối WebSocket bền vững (persistent) đến Server trong suốt vòng đời của phiên làm việc.
2. WHEN kết nối WebSocket bị ngắt đột ngột, THE WebSocket_Client SHALL tự động thử kết nối lại (reconnect) với chiến lược exponential backoff tối đa 5 lần.
3. THE WebSocket_Server SHALL chấp nhận kết nối WebSocket từ Client và gán một `session_id` duy nhất cho mỗi kết nối.
4. THE WebSocket_Server SHALL chỉ nhận dữ liệu dạng JSON text (không nhận raw audio binary) từ Client.
5. IF Client gửi bản tin JSON không hợp lệ (sai schema), THEN THE WebSocket_Server SHALL gửi phản hồi lỗi `{"event": "error", "code": "INVALID_PAYLOAD"}` và duy trì kết nối.

---

### Yêu Cầu 5: Bộ Điều Phối Trung Tâm (Orchestrator)

**User Story:** Là một nhà phát triển, tôi muốn Server có một Orchestrator tích hợp đầy đủ các module AI, để xử lý hội thoại và điều khiển thiết bị một cách nhất quán.

#### Tiêu Chí Chấp Nhận

1. THE Orchestrator SHALL tích hợp đầy đủ 5 module: Context_Manager, Intent_Classifier, Policy_Engine, State_Manager, và Tool_Manager.
2. WHEN Orchestrator nhận Final_Transcript từ Client, THE State_Manager SHALL chuyển trạng thái từ LISTENING sang PROCESSING.
3. WHEN Orchestrator đang ở trạng thái PROCESSING, THE Intent_Classifier SHALL phân loại ý định người dùng sử dụng Gemini Function Calling với danh sách schema hàm điều khiển IoT.
4. WHEN Intent_Classifier trả về một Function Call, THE Policy_Engine SHALL chuyển tiếp lệnh điều khiển đến Tool_Manager để thực thi qua MQTT.
5. WHEN Intent_Classifier trả về văn bản thông thường (không phải Function Call), THE Policy_Engine SHALL bỏ qua bước gọi công cụ và chuyển thẳng sang luồng sinh phản hồi LLM.
6. THE Context_Manager SHALL lưu trữ lịch sử hội thoại trên Redis theo key `session:{session_id}:history` với cửa sổ trượt (sliding window) tối đa 10 lượt hội thoại gần nhất.

---

### Yêu Cầu 6: Sinh Phản Hồi LLM Streaming

**User Story:** Là một người dùng, tôi muốn nhận được phản hồi giọng nói ngay khi chatbot bắt đầu sinh câu trả lời, để giảm thời gian chờ đợi.

#### Tiêu Chí Chấp Nhận

1. WHEN Orchestrator bắt đầu gọi LLM, THE LLM SHALL sinh phản hồi dạng streaming token-by-token sử dụng Gemini 1.5 Flash API.
2. WHEN LLM sinh ra token đầu tiên, THE State_Manager SHALL chuyển trạng thái từ PROCESSING sang SPEAKING.
3. WHEN LLM sinh ra mỗi token mới, THE Orchestrator SHALL chuyển tiếp token đó ngay lập tức đến TTS_Engine mà không chờ hoàn thành toàn bộ câu.
4. THE Orchestrator SHALL cung cấp cho LLM ngữ cảnh đầy đủ bao gồm: lịch sử hội thoại từ Context_Manager, kết quả thực thi IoT (nếu có), và Final_Transcript hiện tại.
5. IF LLM API trả về lỗi hoặc timeout, THEN THE Orchestrator SHALL chuyển State_Manager sang trạng thái ERROR và gửi thông báo lỗi đến Client.

---

### Yêu Cầu 7: Tổng Hợp Giọng Nói TTS Streaming

**User Story:** Là một người dùng, tôi muốn nghe phản hồi bằng giọng nói tiếng Việt tự nhiên được phát ra ngay khi chatbot bắt đầu trả lời, để trải nghiệm hội thoại mượt mà.

#### Tiêu Chí Chấp Nhận

1. WHEN TTS_Engine nhận được token văn bản từ Orchestrator, THE TTS_Engine SHALL tổng hợp âm thanh tiếng Việt sử dụng Edge-TTS theo cơ chế streaming.
2. WHEN TTS_Engine tổng hợp được một chunk âm thanh (40–120ms), THE WebSocket_Server SHALL gửi chunk âm thanh đó ngay lập tức đến Client qua WebSocket mà không chờ hoàn thành toàn bộ câu.
3. WHEN Client nhận được chunk âm thanh TTS đầu tiên, THE Audio_Player SHALL bắt đầu phát âm thanh qua loa ngay lập tức sử dụng `sounddevice`.
4. THE Audio_Player SHALL phát các chunk âm thanh liên tiếp theo thứ tự nhận được để đảm bảo tính liên tục của giọng nói.
5. IF TTS_Engine gặp lỗi trong quá trình tổng hợp, THEN THE Orchestrator SHALL ghi nhận lỗi, dừng luồng TTS và chuyển State_Manager sang trạng thái ERROR.

---

### Yêu Cầu 8: Tính Năng Ngắt Lời (Barge-In)

**User Story:** Là một người dùng, tôi muốn có thể nói chen ngang khi chatbot đang phát âm thanh phản hồi, để cuộc hội thoại trở nên tự nhiên và không bị gián đoạn.

#### Tiêu Chí Chấp Nhận

1. WHILE Audio_Player đang phát âm thanh TTS, THE VAD SHALL tiếp tục thu âm và phân tích microphone để phát hiện giọng nói người dùng.
2. WHEN VAD phát hiện giọng nói liên tục từ microphone trong ít nhất 150ms trong khi Audio_Player đang phát, THE Client SHALL xác định đây là sự kiện Barge_In.
3. WHEN Barge_In được xác nhận, THE Audio_Player SHALL dừng phát âm thanh ngay lập tức và xóa audio buffer cục bộ.
4. WHEN Barge_In được xác nhận, THE WebSocket_Client SHALL gửi bản tin `{"event": "barge_in", "timestamp": <unix_timestamp>}` lên Server.
5. WHEN WebSocket_Server nhận sự kiện `barge_in`, THE Orchestrator SHALL hủy tác vụ LLM streaming và TTS streaming đang chạy sử dụng `asyncio.Task.cancel()`.
6. WHEN Orchestrator hủy xong các tác vụ, THE WebSocket_Server SHALL gửi bản tin `{"event": "clear_buffer"}` về Client để xác nhận.
7. WHEN Client nhận `clear_buffer`, THE State_Manager SHALL chuyển về trạng thái LISTENING và bắt đầu pipeline STT mới cho câu nói chen ngang.
8. THE Client SHALL áp dụng ngưỡng năng lượng động (dynamic energy threshold) để VAD tự động tăng ngưỡng nhận diện khi Audio_Player đang hoạt động, nhằm tránh kích hoạt Barge_In nhầm do tiếng vọng loa.

---

### Yêu Cầu 9: Điều Khiển Thiết Bị IoT qua MQTT

**User Story:** Là một người dùng, tôi muốn ra lệnh bằng giọng nói để bật/tắt và điều chỉnh các thiết bị nhà thông minh, và nhận xác nhận ngay lập tức khi lệnh được thực thi.

#### Tiêu Chí Chấp Nhận

1. WHEN Tool_Manager nhận lệnh điều khiển IoT từ Policy_Engine, THE MQTT_Manager SHALL publish bản tin JSON lên topic `iot/control/{device_id}` với đầy đủ các trường: `command_id`, `action`, `parameters`, `sent_at`.
2. WHEN MQTT_Manager gửi lệnh, THE MQTT_Manager SHALL subscribe topic `iot/status/{device_id}` và đợi phản hồi xác nhận từ ESP32 trong vòng 100ms.
3. WHEN ESP32 thực thi lệnh thành công và gửi phản hồi `{"status": "SUCCESS"}` trước 100ms, THE Tool_Manager SHALL trả kết quả thành công cho Policy_Engine để đưa vào ngữ cảnh LLM.
4. IF ESP32 không gửi phản hồi trong vòng 100ms, THEN THE MQTT_Manager SHALL trả về `{"status": "TIMEOUT"}` và THE Policy_Engine SHALL chèn thông báo lỗi thiết bị vào prompt LLM để thông báo cho người dùng.
5. THE MQTT_Manager SHALL sử dụng `asyncio.Future` để chuyển đổi mô hình publish/subscribe của MQTT thành hàm `awaitable` bất đồng bộ, tránh chặn event loop của Server.

---

### Yêu Cầu 10: Quản Lý Máy Trạng Thái (State Machine)

**User Story:** Là một nhà phát triển, tôi muốn hệ thống Server có máy trạng thái rõ ràng, để kiểm soát luồng xử lý và tránh các trạng thái không nhất quán.

#### Tiêu Chí Chấp Nhận

1. THE State_Manager SHALL quản lý 5 trạng thái hợp lệ: `IDLE`, `LISTENING`, `PROCESSING`, `SPEAKING`, `ERROR`.
2. WHEN kết nối WebSocket mới được thiết lập, THE State_Manager SHALL khởi tạo trạng thái ban đầu là `IDLE`.
3. WHEN State_Manager nhận lệnh chuyển trạng thái không hợp lệ (ví dụ: từ IDLE sang SPEAKING), THE State_Manager SHALL từ chối chuyển trạng thái và ghi nhận cảnh báo vào log.
4. WHEN State_Manager chuyển sang trạng thái `ERROR`, THE Orchestrator SHALL ghi nhận log lỗi chi tiết và gửi thông báo lỗi đến Client.
5. WHEN kết nối WebSocket bị đóng, THE State_Manager SHALL giải phóng tất cả tài nguyên liên quan đến Session và xóa dữ liệu khỏi Redis.

---

### Yêu Cầu 11: Hiệu Suất và Độ Trễ Đầu Cuối

**User Story:** Là một người dùng, tôi muốn nhận được phản hồi giọng nói trong vòng 500ms sau khi kết thúc câu nói, để trải nghiệm hội thoại tự nhiên như nói chuyện với người thật.

#### Tiêu Chí Chấp Nhận

1. THE System SHALL đạt độ trễ đầu cuối (E2E Latency) dưới 500ms, tính từ thời điểm VAD phát hiện kết thúc câu nói đến khi chunk âm thanh TTS đầu tiên phát ra từ loa Client.
2. THE STT_Engine SHALL hoàn thành nhận dạng và gửi Final_Transcript trong vòng 140ms kể từ khi VAD phát hiện kết thúc câu nói.
3. THE LLM SHALL sinh ra token đầu tiên trong vòng 150ms kể từ khi Orchestrator gửi prompt.
4. THE TTS_Engine SHALL tổng hợp và gửi chunk âm thanh đầu tiên trong vòng 90ms kể từ khi nhận token đầu tiên từ LLM.
5. THE System SHALL đạt tỷ lệ lỗi nhận dạng giọng nói (Word Error Rate) dưới 10% trong môi trường thông thường.
6. THE System SHALL đạt tỷ lệ thành công Barge_In trên 95%, với thời gian dừng loa dưới 200ms kể từ khi phát hiện giọng nói chen ngang.
7. THE System SHALL đạt tỷ lệ thành công điều khiển IoT trên 95%, với thời gian phản hồi thiết bị dưới 100ms.

---

### Yêu Cầu 12: Cấu Trúc Thư Mục và Module Hóa

**User Story:** Là một nhà phát triển, tôi muốn codebase được tổ chức theo cấu trúc thư mục tách biệt giữa client/ và server/, để dễ dàng phát triển, kiểm thử và triển khai độc lập.

#### Tiêu Chí Chấp Nhận

1. THE System SHALL tổ chức code theo cấu trúc thư mục tách biệt với thư mục `client/` chứa toàn bộ code phía Client và thư mục `server/` chứa toàn bộ code phía Server.
2. THE Client SHALL tổ chức các module thành các package riêng biệt: `audio/` (thu âm, VAD, phát loa), `wakeword/` (Wake Word detection), `stt/` (STT engine), `transport/` (WebSocket client).
3. THE Server SHALL tổ chức các module thành các package riêng biệt: `api/` (WebSocket endpoint), `orchestrator/` (Orchestrator và các sub-module), `services/` (LLM, TTS, MQTT), `models/` (data models).
4. THE System SHALL cung cấp file `requirements.txt` riêng biệt cho `client/` và `server/` để quản lý dependency độc lập.
