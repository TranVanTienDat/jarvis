# Implementation Plan: Voice Chatbot IoT

## Overview

Triển khai hệ thống Voice Chatbot IoT thời gian thực theo kiến trúc Client–Server tách biệt.
Client chạy trên Raspberry Pi xử lý âm thanh cục bộ (wake word, STT, VAD, playback).
Server FastAPI điều phối AI pipeline (LLM streaming, TTS streaming, MQTT IoT control).
Giao tiếp qua WebSocket full-duplex với mục tiêu E2E latency < 500ms.

## Tasks

- [x] 1. Project scaffolding — cấu trúc thư mục, config, requirements
  - Tạo toàn bộ cây thư mục theo spec: `client/audio/`, `client/wakeword/`, `client/stt/`, `client/transport/`, `server/api/`, `server/orchestrator/`, `server/services/`, `server/models/`
  - Tạo tất cả file `__init__.py` cho mỗi package
  - Tạo `client/config.py` với các hằng số: SAMPLE_RATE, FRAME_DURATION_MS, VAD params, Porcupine keys, STT model ID, SERVER_URI, WS_MAX_RETRIES
  - Tạo `server/config.py` với env vars: HOST, PORT, REDIS_URL, GEMINI_API_KEY, GEMINI_MODEL, TTS_VOICE, MQTT params, LOG_LEVEL
  - Tạo `client/requirements.txt`: sounddevice, webrtcvad, pvporcupine, transformers, websockets, numpy
  - Tạo `server/requirements.txt`: fastapi, uvicorn, redis, google-generativeai, edge-tts, paho-mqtt, pydantic, hypothesis
  - Tạo `.env.example` với template đầy đủ cho cả client và server
  - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [x] 2. Client — Audio modules (capture, VAD, player)
  - [x] 2.1 Implement `client/audio/capture.py` — AudioCapture class
    - Mở `sounddevice.InputStream` với SAMPLE_RATE=16000, channels=1, dtype=int16
    - Callback non-blocking đẩy frame 480 samples (30ms) vào `asyncio.Queue[bytes]`
    - Implement `start()`, `stop()`, `get_frame_queue()` methods
    - _Requirements: 1.1_

  - [ ]\* 2.2 Write property test cho VAD frame length invariant
    - **Property 1: VAD Frame Length Invariant**
    - Với mọi frame bytes, VAD SHALL reject frame không đúng 480 samples
    - **Validates: Requirements 1.2**

  - [x] 2.3 Implement `client/audio/vad.py` — VAD class
    - Bọc `webrtcvad.Vad` với aggressiveness=2
    - Implement `is_speech(frame, sample_rate)` → bool
    - Implement `check_end_of_utterance(frame)` → bool (17 consecutive silence frames)
    - Implement `check_barge_in(frame, speaker_active)` → bool (5 consecutive speech frames)
    - Implement `set_speaker_active(active)` với dynamic energy threshold (multiplier 2.5×)
    - _Requirements: 1.2, 1.3, 8.1, 8.2, 8.8_

  - [ ]\* 2.4 Write property test cho end-of-utterance trigger
    - **Property 2: End-of-Utterance Trigger**
    - Với mọi (speech_frames, silence_frames), EOU fires iff silence_frames >= 17
    - **Validates: Requirements 1.3**

  - [ ]\* 2.5 Write property test cho barge-in threshold
    - **Property 13: Barge-In Threshold**
    - Barge-in fires iff consecutive speech frames >= 5 (150ms) khi speaker_active=True
    - **Validates: Requirements 8.2**

  - [ ]\* 2.6 Write property test cho dynamic VAD threshold
    - **Property 14: Dynamic VAD Threshold**
    - Threshold khi speaker_active=True SHALL > threshold khi speaker_active=False
    - **Validates: Requirements 8.8**

  - [x] 2.7 Implement `client/audio/player.py` — AudioPlayer class
    - Mở `sounddevice.OutputStream` với internal asyncio queue
    - Implement `play_chunk(chunk: bytes)` — enqueue chunk
    - Implement `stop()` — clear queue ngay lập tức (barge-in)
    - Implement `is_playing` property
    - _Requirements: 7.3, 7.4, 8.3_

  - [ ]\* 2.8 Write unit tests cho AudioPlayer
    - Test `stop()` xóa queue ngay lập tức
    - Test `is_playing` trả đúng trạng thái
    - _Requirements: 7.4, 8.3_

- [x] 3. Client — Wake word detector
  - [x] 3.1 Implement `client/wakeword/detector.py` — WakeWordDetector class
    - Bọc `pvporcupine` với keyword "Hey AI"
    - Implement `__init__(access_key, keyword_path)`, `process(pcm_frame)` → bool, `delete()`
    - Chỉ chạy khi state là IDLE; trả True khi phát hiện wake word
    - Xử lý lỗi khởi tạo (thiếu license key, lỗi phần cứng) → log CRITICAL, dừng pipeline
    - _Requirements: 2.1, 2.2, 2.4_

  - [ ]\* 3.2 Write unit tests cho WakeWordDetector
    - Test khởi tạo thành công với valid key
    - Test lỗi khởi tạo với invalid key → raise exception
    - _Requirements: 2.4_

- [x] 4. Client — STT engine
  - [x] 4.1 Implement `client/stt/engine.py` — STTEngine class
    - Load `UsefulSensors/moonshine-tiny-vi` qua `MoonshineForConditionalGeneration`
    - Convert bytes → float32 numpy array, normalize [-1, 1]
    - Implement `transcribe_stream(audio_frames)` → `AsyncIterator[str]` dùng `TextIteratorStreamer`
    - Chạy `model.generate()` trong `ThreadPoolExecutor` để không block event loop
    - Implement `transcribe_final(audio_frames)` → str (join all tokens)
    - Xử lý lỗi inference → gửi `stt_error`, reset về IDLE
    - _Requirements: 3.1, 3.2, 3.5_

  - [ ]\* 4.2 Write unit tests cho STTEngine
    - Test `transcribe_stream` yields tokens incrementally
    - Test `transcribe_final` returns complete string
    - Test error handling → stt_error message
    - _Requirements: 3.1, 3.2, 3.5_

- [x] 5. Client — WebSocket transport
  - [x] 5.1 Implement `client/transport/ws_client.py` — WSClient class
    - Duy trì kết nối WebSocket bền vững đến SERVER_URI
    - Implement `connect()`, `send(message: dict)`, `recv()` → dict, `close()`
    - Implement `_reconnect_with_backoff()`: delay = min(2^n, 60)s, tối đa 5 lần
    - Raise `ConnectionFailed` sau lần thứ 5
    - _Requirements: 4.1, 4.2_

  - [ ]\* 5.2 Write property test cho exponential backoff
    - **Property 5: Reconnect Exponential Backoff**
    - Với mọi attempt n ∈ [1,5], delay = min(2^n, 60). Attempt > 5 → ConnectionFailed
    - **Validates: Requirements 4.2**

  - [ ]\* 5.3 Write unit tests cho WSClient
    - Test reconnect logic với mock WebSocket
    - Test send/recv JSON serialization
    - _Requirements: 4.1, 4.2_

- [x] 6. Client — Main pipeline orchestration
  - [x] 6.1 Implement `client/main.py` — entry point và pipeline state machine
    - Khởi tạo AudioCapture, VAD, WakeWordDetector, STTEngine, WSClient, AudioPlayer
    - Implement state machine: IDLE → (wake word) → LISTENING → (VAD end) → send final_transcript → wait server response
    - IDLE: chỉ chạy WakeWordDetector, không gửi audio lên server
    - LISTENING: chạy STT streaming, gửi partial_transcript tokens, gửi final_transcript khi VAD end
    - SPEAKING: AudioPlayer phát chunks, VAD vẫn chạy để detect barge-in
    - Xử lý `clear_buffer` từ server → chuyển về LISTENING
    - _Requirements: 2.1, 2.2, 2.3, 3.3, 3.4, 7.3, 8.3, 8.7_

  - [ ]\* 6.2 Write property test cho IDLE state audio privacy
    - **Property 3: IDLE State Audio Privacy**
    - Khi state=IDLE, WSClient SHALL gửi zero messages lên server
    - **Validates: Requirements 2.3**

  - [ ]\* 6.3 Write property test cho partial transcript message schema
    - **Property 4: Partial Transcript Message Schema**
    - Với mọi token string, message gửi đi SHALL có event="partial_transcript", token=<token>, valid JSON
    - **Validates: Requirements 3.3**

- [x] 7. Checkpoint — Client modules hoàn chỉnh
  - Ensure all client unit tests pass, ask the user if questions arise.

- [x] 8. Server — Data models và config
  - [x] 8.1 Implement `server/models/schemas.py` — Pydantic models
    - Định nghĩa `SessionState` enum: IDLE, LISTENING, PROCESSING, SPEAKING, ERROR
    - Client→Server messages: `PartialTranscriptMsg`, `FinalTranscriptMsg`, `BargeInMsg`, `STTErrorMsg`
    - `ClientMessage = Union[...]` với Literal discriminator
    - Server→Client messages: `AudioChunkMsg` (data: base64, seq: int), `ClearBufferMsg`, `SessionInitMsg`, `StateChangeMsg`, `ErrorMsg`
    - `ServerMessage = Union[...]`
    - MQTT payloads: `IoTCommand` (command_id, action, parameters, sent_at), `IoTStatus` (command_id, status, current_state, error_message, latency_ms)
    - Internal: `ConversationMessage`, `PolicyResult`
    - _Requirements: 4.4, 9.1_

  - [ ]\* 8.2 Write property test cho invalid payload rejection
    - **Property 7: Invalid Payload Rejection with Connection Preservation**
    - Với mọi invalid JSON/schema message, server SHALL respond INVALID_PAYLOAD và giữ kết nối
    - **Validates: Requirements 4.5**

  - [ ]\* 8.3 Write unit tests cho Pydantic schemas
    - Test serialization/deserialization round-trip cho mỗi message type
    - Test validation errors cho invalid payloads
    - _Requirements: 4.4, 4.5_

- [x] 9. Server — State Manager
  - [x] 9.1 Implement `server/orchestrator/state_manager.py` — StateManager class
    - Định nghĩa `State` enum và `VALID_TRANSITIONS` dict
    - Implement `transition(session_id, new_state)` → bool: từ chối invalid transitions, log WARNING
    - Implement `get_state(session_id)` → State
    - Khởi tạo state=IDLE khi session mới
    - Giải phóng session state khi WebSocket đóng
    - _Requirements: 10.1, 10.2, 10.3, 10.5_

  - [ ]\* 9.2 Write property test cho invalid state transition rejection
    - **Property 17: Invalid State Transition Rejection**
    - Với mọi (current_state, requested_state) không có trong VALID_TRANSITIONS, SHALL reject, state không đổi
    - **Validates: Requirements 10.3**

  - [ ]\* 9.3 Write unit tests cho StateManager
    - Test tất cả valid transitions thành công
    - Test tất cả invalid transitions bị từ chối
    - Test initial state = IDLE
    - _Requirements: 10.1, 10.2, 10.3_

- [x] 10. Server — Context Manager
  - [x] 10.1 Implement `server/orchestrator/context_manager.py` — ContextManager class
    - Kết nối Redis với REDIS_URL từ config
    - Key format: `session:{session_id}:history`
    - Implement `get_history(session_id)` → list[dict]
    - Implement `add_message(session_id, role, content)` với sliding window MAX_HISTORY=10
    - Implement `clear_session(session_id)`
    - Graceful degradation khi Redis không kết nối được (trả empty history, log WARNING)
    - _Requirements: 5.6, 10.5_

  - [ ]\* 10.2 Write property test cho context sliding window
    - **Property 9: Context Sliding Window**
    - Với mọi session > 10 turns, Redis SHALL chứa đúng 10 turns gần nhất, thứ tự preserved
    - **Validates: Requirements 5.6**

  - [ ]\* 10.3 Write unit tests cho ContextManager
    - Test sliding window eviction
    - Test Redis failure → graceful degradation
    - _Requirements: 5.6_

- [x] 11. Server — Intent Classifier và Policy Engine
  - [x] 11.1 Implement `server/orchestrator/intent_classifier.py` — IntentClassifier class
    - Định nghĩa `FunctionCall` và `TextResponse` dataclasses
    - Định nghĩa `IOT_FUNCTION_SCHEMAS` list với Gemini function definitions cho IoT control
    - Implement `classify(text, history)` → `FunctionCall | TextResponse`
    - Gửi transcript + function schemas đến Gemini API
    - _Requirements: 5.3_

  - [x] 11.2 Implement `server/orchestrator/policy_engine.py` — PolicyEngine class
    - Implement `execute(intent, session_id, context)` → PolicyResult
    - Nếu intent là FunctionCall → route đến ToolManager
    - Nếu intent là TextResponse → route thẳng đến LLM, không gọi ToolManager
    - _Requirements: 5.4, 5.5_

  - [ ]\* 11.3 Write property test cho policy engine routing invariant
    - **Property 8: Policy Engine Routing Invariant**
    - FunctionCall → ToolManager (không gọi LLM trực tiếp); TextResponse → LLM (không gọi ToolManager)
    - **Validates: Requirements 5.4, 5.5**

  - [ ]\* 11.4 Write unit tests cho IntentClassifier và PolicyEngine
    - Test FunctionCall routing với mock Gemini response
    - Test TextResponse routing
    - Test policy routing với mock ToolManager và LLM
    - _Requirements: 5.3, 5.4, 5.5_

- [x] 12. Server — LLM Service
  - [x] 12.1 Implement `server/services/llm.py` — LLMService class
    - Khởi tạo Gemini 1.5 Flash client với GEMINI_API_KEY
    - Implement `stream(messages, system_prompt)` → `AsyncIterator[str]` (yields tokens)
    - Xử lý lỗi/timeout Gemini API → raise LLMError
    - _Requirements: 6.1, 6.5_

  - [ ]\* 12.2 Write property test cho LLM token forwarding
    - **Property 10: LLM Token Forwarding Without Buffering**
    - Với mọi token từ LLM stream, Orchestrator SHALL forward ngay (không chờ sentence complete, trừ buffer > 50 chars)
    - **Validates: Requirements 6.3**

  - [ ]\* 12.3 Write unit tests cho LLMService
    - Test streaming với mock Gemini response
    - Test error handling → LLMError
    - _Requirements: 6.1, 6.5_

- [x] 13. Server — TTS Service
  - [x] 13.1 Implement `server/services/tts.py` — TTSService class
    - Sử dụng Edge-TTS với VOICE="vi-VN-HoaiMyNeural"
    - Implement `synthesize_stream(text_stream)` → `AsyncIterator[bytes]` (yields PCM chunks 40–120ms)
    - Token buffering: flush khi gặp sentence boundary hoặc buffer > 50 chars
    - Xử lý lỗi TTS → raise TTSError
    - _Requirements: 7.1, 7.2, 7.5_

  - [ ]\* 13.2 Write property test cho TTS audio chunk ordering
    - **Property 12: TTS Audio Chunk Ordering**
    - Với mọi sequence audio chunks, AudioPlayer SHALL play theo đúng thứ tự seq number
    - **Validates: Requirements 7.4**

  - [ ]\* 13.3 Write unit tests cho TTSService
    - Test synthesize_stream yields chunks
    - Test sentence boundary buffering
    - Test error handling → TTSError
    - _Requirements: 7.1, 7.2_

- [x] 14. Server — MQTT Manager
  - [x] 14.1 Implement `server/services/mqtt_manager.py` — MQTTManager class
    - Bọc `paho-mqtt` với `asyncio.Future` pattern
    - Implement `send_command(device_id, parameters)` → dict
    - Publish lên `iot/control/{device_id}` với đầy đủ fields: command_id, action, parameters, sent_at
    - Subscribe `iot/status/{device_id}`, đợi response với timeout 100ms
    - Trả `{"status": "SUCCESS", ...}` hoặc `{"status": "TIMEOUT", ...}`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [ ]\* 14.2 Write property test cho MQTT command message completeness
    - **Property 15: MQTT Command Message Completeness**
    - Với mọi IoT command, MQTT message SHALL có đủ 4 fields: command_id, action, parameters, sent_at
    - **Validates: Requirements 9.1**

  - [ ]\* 14.3 Write property test cho MQTT timeout correctness
    - **Property 16: MQTT Timeout Correctness**
    - Response < 100ms → SUCCESS; no response trong 100ms → TIMEOUT; response sau 100ms không được tính SUCCESS
    - **Validates: Requirements 9.2, 9.3, 9.4**

  - [ ]\* 14.4 Write unit tests cho MQTTManager
    - Test asyncio.Future pattern với mock paho-mqtt
    - Test timeout behavior
    - _Requirements: 9.5_

- [x] 15. Server — Tool Manager
  - [x] 15.1 Implement `server/orchestrator/tool_manager.py` — ToolManager class
    - Implement `trigger_iot_action(device_id, action, parameters)` → IoTResult
    - Gọi MQTTManager.send_command(), xử lý SUCCESS và TIMEOUT
    - Implement `query_weather(location)` → WeatherResult (gọi weather API)
    - _Requirements: 5.4, 9.3, 9.4_

  - [ ]\* 15.2 Write unit tests cho ToolManager
    - Test IoT action với mock MQTTManager (SUCCESS case)
    - Test IoT action với mock MQTTManager (TIMEOUT case)
    - _Requirements: 9.3, 9.4_

- [x] 16. Server — Orchestrator core
  - [x] 16.1 Implement `server/orchestrator/core.py` — Orchestrator class
    - Nhận 5 sub-module qua constructor: ContextManager, IntentClassifier, PolicyEngine, StateManager, ToolManager
    - Implement `handle_final_transcript(session_id, text, websocket)`:
      - StateManager: LISTENING → PROCESSING
      - ContextManager.get_history()
      - IntentClassifier.classify()
      - PolicyEngine.execute()
      - LLM streaming → TTS streaming → gửi audio_chunk messages
      - StateManager: PROCESSING → SPEAKING → IDLE
      - ContextManager.add_message()
    - Implement `handle_barge_in(session_id)`: cancel LLM/TTS tasks, gửi clear_buffer
    - Implement `_register_task()` và `_cancel_task()` với asyncio.Task
    - Ghi latency timestamps tại các mốc xử lý
    - _Requirements: 5.1, 5.2, 6.2, 6.3, 6.4, 8.5, 8.6_

  - [ ]\* 16.2 Write property test cho LLM prompt completeness
    - **Property 11: LLM Prompt Completeness**
    - Với mọi (history, iot_result, final_transcript), prompt SHALL chứa đủ 3 thành phần
    - **Validates: Requirements 6.4**

  - [ ]\* 16.3 Write unit tests cho Orchestrator
    - Test full pipeline với mock services
    - Test barge-in cancels LLM/TTS tasks
    - Test error propagation → ERROR state
    - _Requirements: 5.1, 5.2, 8.5, 8.6_

- [x] 17. Server — WebSocket API handler và main app
  - [x] 17.1 Implement `server/api/ws_handler.py` — WSHandler class và endpoint
    - FastAPI WebSocket endpoint tại `/ws/chat`
    - Gán `session_id = uuid4()` cho mỗi kết nối mới
    - Gửi `session_init` message với session_id
    - Validate JSON với Pydantic `ClientMessage` union type
    - Dispatch events đến Orchestrator: `final_transcript`, `barge_in`, `stt_error`
    - Xử lý invalid payload → gửi INVALID_PAYLOAD error, giữ kết nối
    - Cleanup session khi WebSocket đóng
    - _Requirements: 4.3, 4.4, 4.5, 10.2, 10.5_

  - [ ]\* 17.2 Write property test cho session ID uniqueness
    - **Property 6: Session ID Uniqueness**
    - Với mọi tập concurrent connections, tất cả session_id SHALL globally unique
    - **Validates: Requirements 4.3**

  - [x] 17.3 Implement `server/main.py` — FastAPI app entry point
    - Khởi tạo FastAPI app, include WebSocket router
    - Khởi tạo dependency injection: Redis client, MQTTManager, tất cả services và orchestrator
    - Uvicorn entry point với HOST, PORT từ config
    - _Requirements: 12.3_

  - [ ]\* 17.4 Write unit tests cho WSHandler
    - Test session_id assignment và session_init message
    - Test invalid JSON → INVALID_PAYLOAD, connection preserved
    - Test WebSocket cleanup on disconnect
    - _Requirements: 4.3, 4.5, 10.5_

- [x] 18. Checkpoint — Server modules hoàn chỉnh
  - Ensure all server unit tests pass, ask the user if questions arise.

- [x] 19. Property-based tests — Hypothesis test suite
  - [x] 19.1 Tạo `tests/test_properties.py` — file tổng hợp tất cả property tests
    - Setup Hypothesis settings: max_examples=200 cho mỗi property
    - Import các module cần test từ client và server
    - Annotate mỗi test với tag: `# Feature: voice-chatbot-iot, Property {N}: {title}`
    - _Requirements: 1.2, 1.3, 2.3, 3.3, 4.2, 4.3, 4.5, 5.4, 5.5, 5.6, 6.3, 6.4, 7.4, 8.2, 8.8, 9.1, 9.2, 10.3_

  - [ ]\* 19.2 Write remaining property tests chưa có sub-task riêng
    - Không có property nào còn thiếu — tất cả 17 properties đã được phân bổ vào các task tương ứng

- [x] 20. Integration tests
  - [x] 20.1 Tạo `tests/test_integration.py` — integration test suite
    - Test WebSocket connection lifecycle: connect → session_init → disconnect
    - Test full pipeline latency: final_transcript → first audio_chunk (target < 500ms) với mock LLM/TTS
    - Test MQTT round-trip: publish command → receive status (target < 100ms) với mock broker
    - Test barge-in end-to-end: detect → stop speaker → cancel tasks → clear_buffer (target < 200ms)
    - Test WebSocket reconnect: simulate disconnect → verify reconnect với backoff
    - Test concurrent sessions: 10 sessions đồng thời, verify session isolation
    - _Requirements: 4.1, 4.2, 8.5, 8.6, 8.7, 9.2, 11.1_

  - [ ]\* 20.2 Write smoke tests
    - Test sounddevice stream mở được với đúng thông số (16kHz, mono, int16)
    - Test StateManager có đúng 5 trạng thái hợp lệ
    - Test Orchestrator instance có đủ 5 sub-module attributes
    - Test MQTTManager sử dụng asyncio.Future pattern
    - Test cấu trúc thư mục client/ và server/ tồn tại đúng theo spec
    - _Requirements: 12.1, 12.2, 12.3_

- [x] 21. Final checkpoint — Toàn bộ test suite pass
  - Ensure all tests pass (unit, property-based, integration, smoke), ask the user if questions arise.

## Notes

- Tasks đánh dấu `*` là optional — có thể bỏ qua để MVP nhanh hơn
- Mỗi task tham chiếu requirements cụ thể để đảm bảo traceability
- Property-based tests dùng Hypothesis với `@given` decorator, min 200 iterations mỗi property
- Unit tests dùng pytest với mock cho external services (Gemini, Edge-TTS, MQTT, Redis)
- Checkpoints tại task 7, 18, 21 đảm bảo validation incremental
- Client và server có thể phát triển song song sau khi hoàn thành task 1 (scaffolding)
- Tất cả 17 Correctness Properties từ design.md đều được cover bởi property test sub-tasks

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    {
      "id": 1,
      "tasks": ["2.1", "2.3", "2.7", "3.1", "4.1", "5.1", "8.1", "9.1", "10.1"]
    },
    {
      "id": 2,
      "tasks": [
        "2.2",
        "2.4",
        "2.5",
        "2.6",
        "2.8",
        "3.2",
        "4.2",
        "5.2",
        "5.3",
        "8.2",
        "8.3",
        "9.2",
        "9.3",
        "10.2",
        "10.3"
      ]
    },
    {
      "id": 3,
      "tasks": ["6.1", "11.1", "11.2", "12.1", "13.1", "14.1", "15.1"]
    },
    {
      "id": 4,
      "tasks": [
        "6.2",
        "6.3",
        "11.3",
        "11.4",
        "12.2",
        "12.3",
        "13.2",
        "13.3",
        "14.2",
        "14.3",
        "14.4",
        "15.2"
      ]
    },
    { "id": 5, "tasks": ["16.1"] },
    { "id": 6, "tasks": ["16.2", "16.3", "17.1"] },
    { "id": 7, "tasks": ["17.2", "17.3", "17.4"] },
    { "id": 8, "tasks": ["19.1", "20.1"] },
    { "id": 9, "tasks": ["19.2", "20.2"] }
  ]
}
```
