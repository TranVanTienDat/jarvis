# Requirements Document

## Introduction

Feature này tích hợp mô hình Speech-to-Text `UsefulSensors/moonshine-tiny-vi` (chạy qua thư viện `transformers`) trực tiếp trên thiết bị Client (Raspberry Pi / Edge device) của hệ thống Voice Chatbot IoT thời gian thực. Thay vì gửi toàn bộ luồng audio thô lên Server để xử lý STT (Deepgram / Faster-Whisper), Client sẽ tự thực hiện nhận dạng giọng nói cục bộ (local inference) và chỉ gửi transcript văn bản lên Server. Điều này giảm băng thông mạng, tăng tính riêng tư, và giảm phụ thuộc vào kết nối internet cho bước STT. Feature phải tích hợp liền mạch với pipeline VAD (`webrtcvad`) và Wake Word (`pvporcupine`) hiện có, đồng thời đảm bảo KPI E2E Latency < 500ms và WER < 10%.

---

## Glossary

- **STT_Engine**: Module phần mềm chạy trên Client, thực hiện nhận dạng giọng nói cục bộ bằng mô hình `moonshine-tiny-vi` thông qua thư viện `transformers`.
- **VAD**: Bộ phát hiện giọng nói (Voice Activity Detection) chạy cục bộ trên Client, sử dụng thư viện `webrtcvad`.
- **Wake_Word_Detector**: Module phát hiện từ khóa kích hoạt chạy cục bộ trên Client, sử dụng thư viện `pvporcupine`.
- **Audio_Buffer**: Vùng bộ nhớ tạm trên Client lưu trữ các audio chunk PCM trong khoảng thời gian từ khi VAD phát hiện bắt đầu giọng nói đến khi phát hiện kết thúc câu nói.
- **Transcript**: Chuỗi văn bản UTF-8 kết quả nhận dạng giọng nói do STT_Engine tạo ra.
- **WebSocket_Client**: Module quản lý kết nối WebSocket bất đồng bộ từ Client đến Server, sử dụng thư viện `websockets`.
- **Client_State_Machine**: Máy trạng thái phía Client với các trạng thái: `IDLE`, `LISTENING`, `PROCESSING`, `SPEAKING`, `ERROR`.
- **Server**: Máy chủ FastAPI trung tâm điều phối (Orchestrator) nhận Transcript từ Client và xử lý LLM, TTS, IoT.
- **Inference_Latency**: Thời gian tính từ khi STT_Engine nhận đầu vào audio đến khi trả về Transcript hoàn chỉnh.
- **E2E_Latency**: Độ trễ đầu cuối, tính từ khi người dùng kết thúc câu nói (VAD phát hiện khoảng lặng) đến khi âm thanh phản hồi đầu tiên phát ra từ loa.
- **WER**: Word Error Rate — tỷ lệ lỗi chữ (thay thế, chèn, xóa) trên tổng số chữ thực tế được nói.
- **PCM_Audio**: Dữ liệu âm thanh thô định dạng PCM Signed 16-bit Little Endian, 16kHz, Mono.
- **Barge_In_Event**: Sự kiện được gửi từ Client lên Server khi VAD phát hiện giọng nói liên tục > 150ms trong khi Client đang ở trạng thái `SPEAKING`.
- **Model_Cache**: Bộ nhớ đệm lưu trữ mô hình `moonshine-tiny-vi` đã được nạp vào RAM để tránh tải lại mỗi lần sử dụng.

---

## Requirements

### Requirement 1: Nạp và Khởi Tạo Mô Hình STT Cục Bộ

**User Story:** As a system operator, I want the STT_Engine to load the `moonshine-tiny-vi` model once at startup, so that inference latency is not impacted by repeated model loading.

#### Acceptance Criteria

1. WHEN the Client application starts, THE STT_Engine SHALL load the `moonshine-tiny-vi` model from the local filesystem into Model_Cache within 30 seconds.
2. WHEN the model files are not found on the local filesystem, THEN THE STT_Engine SHALL log an error message specifying the missing file path and transition the Client_State_Machine to the `ERROR` state.
3. WHEN the available RAM on the device is less than 512MB at model load time, THEN THE STT_Engine SHALL log a warning message indicating insufficient memory and transition the Client_State_Machine to the `ERROR` state.
4. THE STT_Engine SHALL reuse the Model_Cache for all subsequent inference calls without reloading the model from disk.

---

### Requirement 2: Thu Âm và Tích Lũy Audio Buffer

**User Story:** As a user, I want the system to capture my speech accurately after the wake word is detected, so that the STT engine receives complete audio for transcription.

#### Acceptance Criteria

1. WHEN the Wake_Word_Detector detects the configured wake word, THE Client_State_Machine SHALL transition from `IDLE` to `LISTENING` and THE Audio_Buffer SHALL be cleared and initialized.
2. WHILE the Client_State_Machine is in the `LISTENING` state, THE Audio_Buffer SHALL accumulate PCM_Audio chunks of 20–40ms duration sampled at 16kHz, 16-bit, Mono.
3. WHILE the Client_State_Machine is in the `LISTENING` state, THE VAD SHALL evaluate each incoming PCM_Audio frame of 10, 20, or 30ms duration to determine voice activity.
4. WHEN the VAD detects continuous silence exceeding 500ms after a period of detected speech, THE Client_State_Machine SHALL transition from `LISTENING` to `PROCESSING` and THE Audio_Buffer SHALL be finalized for STT inference.
5. WHEN the Audio_Buffer duration exceeds 30 seconds without VAD detecting end-of-speech, THEN THE STT_Engine SHALL process the accumulated Audio_Buffer immediately and THE Client_State_Machine SHALL transition to `PROCESSING`.

---

### Requirement 3: Thực Hiện Nhận Dạng Giọng Nói Cục Bộ

**User Story:** As a user, I want my speech to be transcribed locally on the device, so that the system works with low latency and without sending raw audio to the server.

#### Acceptance Criteria

1. WHEN the Client_State_Machine transitions to `PROCESSING`, THE STT_Engine SHALL perform inference on the finalized Audio_Buffer using the `moonshine-tiny-vi` model loaded in Model_Cache.
2. THE STT_Engine SHALL produce a Transcript as a UTF-8 encoded string from the Audio_Buffer input.
3. WHEN the Audio_Buffer contains only non-speech audio (noise, silence), THEN THE STT_Engine SHALL return an empty Transcript string and THE Client_State_Machine SHALL transition back to `IDLE`.
4. THE STT_Engine SHALL complete inference and produce a Transcript within 400ms for Audio_Buffer durations up to 10 seconds on a Raspberry Pi 4 Model B with 4GB RAM.
5. WHERE the device CPU has more than 2 available cores, THE STT_Engine SHALL configure the `transformers` inference runtime to utilize a maximum of 2 CPU threads to avoid starving the VAD and Wake_Word_Detector processes.

---

### Requirement 4: Gửi Transcript Lên Server

**User Story:** As a system integrator, I want the client to send only the transcript text to the server instead of raw audio, so that network bandwidth consumption is reduced.

#### Acceptance Criteria

1. WHEN the STT_Engine produces a non-empty Transcript, THE WebSocket_Client SHALL send a JSON message to the Server in the format `{"event": "transcript", "text": "<transcript_string>", "timestamp": <unix_ms>}` within 50ms of inference completion.
2. WHEN the Transcript is an empty string, THE WebSocket_Client SHALL NOT send any message to the Server and THE Client_State_Machine SHALL transition to `IDLE`.
3. WHILE the WebSocket_Client is not connected to the Server, THE Client_State_Machine SHALL buffer the Transcript locally and SHALL retry sending after reconnection is established.
4. THE WebSocket_Client SHALL send the Transcript message as a UTF-8 encoded text frame over the existing WebSocket connection without establishing a new connection.

---

### Requirement 5: Đảm Bảo KPI Độ Trễ Đầu Cuối

**User Story:** As a user, I want the system to respond within 500ms after I finish speaking, so that the conversation feels natural and real-time.

#### Acceptance Criteria

1. THE STT_Engine SHALL complete inference on Audio_Buffer durations of 3 seconds or less within 200ms on a Raspberry Pi 4 Model B with 4GB RAM, measured from the moment the Audio_Buffer is finalized to the moment the Transcript is available.
2. THE STT_Engine SHALL complete inference on Audio_Buffer durations between 3 seconds and 10 seconds within 400ms on a Raspberry Pi 4 Model B with 4GB RAM.
3. WHEN the Inference_Latency exceeds 400ms for any single inference call, THE STT_Engine SHALL log a warning message including the Audio_Buffer duration and the measured Inference_Latency in milliseconds.
4. THE Client_State_Machine SHALL record a timestamp at the moment VAD detects end-of-speech (T0) and a timestamp at the moment the Transcript is sent to the Server (T_stt), and THE STT_Engine SHALL ensure that (T_stt - T0) is less than 450ms for Audio_Buffer durations up to 10 seconds.

---

### Requirement 6: Đảm Bảo KPI Độ Chính Xác (WER)

**User Story:** As a user, I want the speech recognition to be accurate for Vietnamese, so that the system understands my commands correctly.

#### Acceptance Criteria

1. THE STT_Engine SHALL produce Transcripts with a Word Error Rate (WER) of less than 10% when processing Vietnamese speech audio recorded in a typical indoor environment with ambient noise level below 60dB SPL.
2. WHEN the STT_Engine produces a Transcript with confidence metadata available from the `transformers` model output, THE STT_Engine SHALL include a `"confidence"` field in the JSON message sent to the Server.
3. THE STT_Engine SHALL normalize the Transcript output by removing leading and trailing whitespace characters before sending to the Server.

---

### Requirement 7: Tích Hợp Với Pipeline VAD và Wake Word Hiện Có

**User Story:** As a developer, I want the STT engine to integrate with the existing VAD and wake word pipeline without breaking current behavior, so that the system upgrade is backward compatible.

#### Acceptance Criteria

1. THE STT_Engine SHALL operate as an independent module that receives the finalized Audio_Buffer from the VAD pipeline without modifying the VAD or Wake_Word_Detector source code.
2. WHILE the Client_State_Machine is in the `IDLE` state, THE STT_Engine SHALL NOT perform any inference operations and SHALL NOT consume CPU resources beyond idle model memory retention.
3. WHILE the Client_State_Machine is in the `SPEAKING` state, THE STT_Engine SHALL NOT perform any inference operations.
4. THE STT_Engine SHALL accept PCM_Audio data in the format produced by `sounddevice` (numpy float32 array or int16 array at 16kHz, Mono) and SHALL perform any required format conversion internally before passing data to the `transformers` model.
5. WHEN the Client_State_Machine transitions to `ERROR`, THE STT_Engine SHALL release all active inference resources and SHALL log the error cause with a timestamp.

---

### Requirement 8: Xử Lý Barge-In Khi Đang Phát Âm Thanh

**User Story:** As a user, I want to interrupt the chatbot while it is speaking, so that I can give a new command without waiting for it to finish.

#### Acceptance Criteria

1. WHILE the Client_State_Machine is in the `SPEAKING` state, THE VAD SHALL continuously evaluate incoming PCM_Audio frames from the microphone.
2. WHEN the VAD detects continuous voice activity exceeding 150ms while the Client_State_Machine is in the `SPEAKING` state, THE WebSocket_Client SHALL immediately send `{"event": "barge_in", "timestamp": <unix_ms>}` to the Server.
3. WHEN the Barge_In_Event is sent, THE Client_State_Machine SHALL immediately stop audio playback, clear the local audio output buffer, and transition to `LISTENING`.
4. WHEN the Client_State_Machine transitions to `LISTENING` after a Barge_In_Event, THE Audio_Buffer SHALL be cleared and THE STT_Engine SHALL be ready to accumulate new PCM_Audio for the next inference.
5. WHEN the Client receives a `{"event": "clear_buffer"}` message from the Server after a Barge_In_Event, THE WebSocket_Client SHALL acknowledge the server-side cancellation and THE Client_State_Machine SHALL remain in `LISTENING` state.

---

### Requirement 9: Khả Năng Chuyển Đổi Giữa STT Cục Bộ và STT Trên Server

**User Story:** As a system operator, I want to switch between local STT (moonshine) and server-side STT (Deepgram/Faster-Whisper) without redeploying the client, so that I can fall back to server STT if local inference performance degrades.

#### Acceptance Criteria

1. THE Client_State_Machine SHALL read an `STT_MODE` configuration parameter at startup with valid values `"local"` and `"server"`.
2. WHEN `STT_MODE` is set to `"local"`, THE STT_Engine SHALL perform local inference using `moonshine-tiny-vi` and THE WebSocket_Client SHALL send only Transcript text to the Server.
3. WHEN `STT_MODE` is set to `"server"`, THE WebSocket_Client SHALL stream raw PCM_Audio chunks to the Server as binary WebSocket frames, preserving the existing behavior, and THE STT_Engine SHALL NOT perform any inference.
4. WHEN `STT_MODE` contains an unrecognized value, THEN THE Client_State_Machine SHALL log an error message specifying the invalid value and SHALL default to `STT_MODE = "server"` to preserve backward compatibility.
5. THE `STT_MODE` configuration parameter SHALL be readable from an environment variable named `ZENTA_STT_MODE` without requiring application restart to take effect on the next session initialization.

---

### Requirement 10: Ghi Log và Giám Sát Hiệu Năng

**User Story:** As a developer, I want the STT engine to log performance metrics, so that I can monitor inference latency and detect regressions in production.

#### Acceptance Criteria

1. THE STT_Engine SHALL log the following metrics for each inference call: Audio_Buffer duration in milliseconds, Inference_Latency in milliseconds, Transcript character count, and a UTC timestamp in ISO 8601 format.
2. WHEN Inference_Latency exceeds 400ms, THE STT_Engine SHALL log the entry at WARNING level; otherwise THE STT_Engine SHALL log at DEBUG level.
3. THE STT_Engine SHALL write log entries to a rotating log file at the path `./logs/stt_engine.log` with a maximum file size of 10MB and a maximum of 5 rotated backup files.
4. IF the log directory does not exist at startup, THEN THE STT_Engine SHALL create the directory before writing the first log entry.
5. THE STT_Engine SHALL expose a method `get_performance_stats()` that returns a dictionary containing the count of total inference calls, mean Inference_Latency, and maximum Inference_Latency since the last application start.
