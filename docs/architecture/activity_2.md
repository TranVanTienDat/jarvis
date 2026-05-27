# Sơ Đồ Hoạt Động Hệ Thống

**Jarvis — Real-time Voice Chatbot IoT (Full-Duplex)**

---

## 1. Kiến Trúc Tổng Thể

```mermaid
graph TB
    subgraph CLIENT["📱 THIẾT BỊ CLIENT (IoT Device / Raspberry Pi)"]
        direction TB
        MIC["🎤 Microphone\n16kHz · 16-bit PCM"]
        AC["AudioCapture\nsounddevice · 30ms frames"]
        WW["WakeWordDetector\nopenWakeWord (ONNX, offline)\nModel: hey_jarvis · Threshold: 0.5"]
        VAD["VAD\nwebrtcvad\nEnd-of-utterance: 510ms\nBarge-in: 150ms"]
        STT["STTEngine (Local)\nmoonshine-tiny-vi\nVietnamese ASR · Streaming"]
        WSC["WSClient\nWebSocket · Exponential Backoff\n5 retries · max 60s"]
        PLAYER["AudioPlayer\nPCM playback\nBarge-in detection"]

        MIC --> AC --> VAD --> WW
        WW -->|"Wake word detected"| STT
        STT -->|"partial / final transcript"| WSC
        WSC -->|"audio_chunk (base64 PCM)"| PLAYER
    end

    subgraph SERVER["🖥️ MÁY CHỦ (FastAPI · Uvicorn)"]
        direction TB
        WSH["WSHandler\n/ws/chat\nPydantic discriminated union\nSession ID (UUID4)"]

        subgraph ORCH["🧠 Orchestrator"]
            direction TB
            SM["StateManager\nIDLE → LISTENING\n→ PROCESSING → SPEAKING"]
            CM["ContextManager\nRedis · sliding window 10 msgs\nGraceful degrade if Redis down"]
            IC["IntentClassifier\nGemini Function Calling\nFunctionCall / TextResponse"]
            PE["PolicyEngine\nRoute: IoT tool vs LLM direct"]
            TM["ToolManager\nMQTT publish · await ack"]
            LLM["LLMService\nStreaming tokens"]
            TTS["TTSService\nEdge-TTS · sentence-boundary buffer\nvi-VN-HoaiMyNeural"]
        end

        subgraph LLMFACTORY["LLM Provider Factory"]
            direction LR
            P1["Gemini"]
            P2["OpenAI"]
            P3["OpenRouter"]
            P4["Grok"]
            P5["Together"]
            P6["DeepSeek"]
            P7["HuggingFace"]
        end

        WSH --> SM
        WSH --> IC
        IC -->|"FunctionCall"| PE
        IC -->|"TextResponse"| PE
        PE -->|"IoT intent"| TM
        PE -->|"chat intent"| LLM
        TM -->|"IoT result + context"| LLM
        LLM -->|"token stream"| TTS
        TTS -->|"PCM chunks"| WSH
        CM -.->|"history"| IC
        LLM -.-> LLMFACTORY
    end

    subgraph IOT["⚡ LỚP IoT"]
        direction TB
        MQTT["MQTT Broker\nMosquitto\niot/control/{device_id}\niot/status/{device_id}"]
        LIGHT["💡 Đèn\ncontrol_light\nESP32/ESP8266"]
        AC2["❄️ Điều hòa\ncontrol_ac\nESP32"]
        LOCK["🔒 Khóa cửa\ncontrol_lock\nESP32"]

        MQTT --> LIGHT & AC2 & LOCK
        LIGHT & AC2 & LOCK -->|"status ack"| MQTT
    end

    subgraph EXT["☁️ DỊCH VỤ NGOÀI"]
        direction LR
        GEMINI["Google Gemini\nIntent + LLM"]
        EDGETTS["Edge-TTS\nMicrosoft · Vietnamese"]
        REDIS["Redis\nConversation history"]
        ONNX["openWakeWord\nONNX · Offline"]
    end

    WSC <-->|"WebSocket\nFull-Duplex"| WSH
    TM <-->|"MQTT · paho-mqtt\nTimeout: 100ms"| MQTT
    IC -.-> GEMINI
    LLM -.-> GEMINI
    TTS -.-> EDGETTS
    CM -.-> REDIS
    WW -.-> ONNX
```

---

## 2. Luồng Happy Path — Điều Khiển IoT

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 Người dùng
    participant Client as 📱 Client
    participant WW as 🔍 WakeWord
    participant STT as 🎙️ STT
    participant Server as 🖥️ Server (WS)
    participant Orch as 🧠 Orchestrator
    participant Redis as 🗄️ Redis
    participant Gemini as 🤖 Gemini
    participant MQTT as 📡 MQTT
    participant ESP as 📟 ESP32
    participant TTS as 🗣️ TTS

    Note over Client,WW: Trạng thái: IDLE

    User->>Client: Nói "Hey Jarvis"
    Client->>WW: PCM frames (80ms liên tục)
    WW-->>Client: ✅ Wake word detected (score > 0.5)
    Note over Client: IDLE → LISTENING

    User->>Client: "Bật đèn phòng khách lên"
    Client->>Client: VAD buffer speech frames
    Client->>Client: End-of-utterance (510ms im lặng)

    Client->>STT: audio_frames[]
    STT-->>Server: partial_transcript (streaming tokens)
    STT-->>Server: final_transcript "Bật đèn phòng khách lên"

    Server->>Orch: dispatch final_transcript
    Note over Orch: LISTENING → PROCESSING

    Orch->>Redis: get_history(session_id)
    Redis-->>Orch: last 10 messages

    Orch->>Gemini: classify intent (Function Calling)
    Gemini-->>Orch: FunctionCall(control_light, {device_id, power="ON"})

    Orch->>MQTT: publish iot/control/light_livingroom
    Note over MQTT,ESP: {command_id, action, parameters, sent_at}
    MQTT->>ESP: Lệnh bật đèn
    ESP->>ESP: Bật đèn ✅
    ESP-->>MQTT: iot/status/light_livingroom → SUCCESS
    MQTT-->>Orch: IoTStatus {status=SUCCESS, latency=45ms}

    Note over Orch: PROCESSING → SPEAKING

    Orch->>Gemini: stream(context + IoT result)
    loop Streaming tokens → TTS → Audio
        Gemini-->>TTS: token
        TTS->>TTS: Buffer đến sentence boundary (.!?)
        TTS-->>Server: PCM audio chunk
        Server-->>Client: audio_chunk (base64)
        Client->>Client: AudioPlayer.play_chunk()
    end

    Client->>User: 🔈 "Dạ, em đã bật đèn phòng khách rồi ạ."

    Orch->>Redis: save turn (user + assistant)
    Note over Orch,Client: SPEAKING → IDLE
```

---

## 3. Luồng Barge-In — Ngắt Lời

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 Người dùng
    participant Client as 📱 Client
    participant VAD as 🔊 VAD
    participant Server as 🖥️ Server
    participant Task as ⚡ asyncio.Task

    Note over Client: Trạng thái: SPEAKING — loa đang phát

    User->>Client: Nói trong khi loa đang phát
    Client->>VAD: audio frame
    VAD->>VAD: Phát hiện 150ms speech liên tục
    VAD-->>Client: barge_in = True

    Client->>Client: AudioPlayer.stop()
    Client->>Server: {event: "barge_in", timestamp}
    Note over Client: SPEAKING → LISTENING

    Server->>Task: task.cancel()
    Task-->>Server: CancelledError (LLM/TTS dừng)

    Server->>Client: {event: "clear_buffer"}
    Note over Server: StateManager → LISTENING

    Client->>Client: Reset speech_buffer + VAD.reset()
    Note over Client: Sẵn sàng nhận câu lệnh mới
```

---

## 4. State Machine

```mermaid
stateDiagram-v2
    direction LR

    [*] --> IDLE : Khởi động

    state CLIENT {
        IDLE --> LISTENING : Wake word detected
        LISTENING --> LISTENING : STT running
        LISTENING --> SPEAKING : audio_chunk received
        SPEAKING --> LISTENING : Barge-in detected
        SPEAKING --> IDLE : Playback complete
        IDLE --> ERROR : Init failed
        LISTENING --> ERROR : STT error
        ERROR --> IDLE : Reset
    }

    state SERVER {
        s_IDLE --> s_LISTENING : WebSocket connected
        s_LISTENING --> s_PROCESSING : final_transcript
        s_PROCESSING --> s_SPEAKING : First audio chunk sent
        s_SPEAKING --> s_IDLE : Turn complete
        s_PROCESSING --> s_LISTENING : barge_in
        s_SPEAKING --> s_LISTENING : barge_in
        s_PROCESSING --> s_ERROR : LLM / TTS error
        s_ERROR --> s_IDLE : Reset
    }
```

---

## 5. Luồng Dữ Liệu Chi Tiết

```mermaid
flowchart TD
    A([🎤 Mic input\n16kHz PCM]) --> B[AudioCapture\n30ms frames]
    B --> C{VAD\nwebrtcvad}

    C -->|Idle: no speech| D[WakeWordDetector\nopenWakeWord ONNX]
    D -->|Not detected| C
    D -->|hey_jarvis ✅| E[STTEngine\nmoonshine-tiny-vi]

    C -->|Active: speech| E
    E -->|partial tokens| F[WSClient\nWebSocket]
    E -->|final transcript| F

    F -->|final_transcript| G[WSHandler\n/ws/chat]
    G --> H[Orchestrator]

    H --> I[ContextManager\nRedis history]
    I --> J[IntentClassifier\nGemini Function Calling]

    J -->|FunctionCall| K[PolicyEngine]
    J -->|TextResponse| K

    K -->|IoT intent| L[ToolManager]
    L -->|MQTT publish| M[MQTT Broker]
    M -->|command| N[ESP32]
    N -->|ack / status| M
    M -->|IoTStatus| L
    L -->|result + context| O[LLMService]

    K -->|chat intent| O

    O -->|token stream| P[TTSService\nEdge-TTS\nsentence-boundary buffer]
    P -->|PCM chunks| Q[WSHandler\naudio_chunk base64]
    Q -->|WebSocket| R[AudioPlayer\nPCM playback]
    R --> S([🔈 Loa phát])

    H --> T[ContextManager\nsave turn → Redis]
```

---

## 6. Tóm Tắt Thành Phần

| Thành phần | Công nghệ                       | Vai trò                                            |
| ---------- | ------------------------------- | -------------------------------------------------- |
| Wake Word  | openWakeWord (ONNX, offline)    | Phát hiện "hey_jarvis" không cần mạng              |
| STT        | moonshine-tiny-vi (HuggingFace) | Nhận dạng tiếng Việt local, streaming              |
| VAD        | webrtcvad                       | End-of-utterance 510ms · Barge-in 150ms            |
| Transport  | WebSocket (FastAPI + Uvicorn)   | Full-duplex, real-time, JSON + binary              |
| Intent     | Gemini Function Calling         | Phân loại IoT command vs chat                      |
| LLM        | Gemini (+ 6 providers)          | Sinh câu trả lời, streaming tokens                 |
| TTS        | Edge-TTS · vi-VN-HoaiMyNeural   | Giọng nói tiếng Việt, sentence-boundary buffer     |
| IoT Bus    | MQTT (Mosquitto + paho-mqtt)    | Điều khiển ESP32, request/response · timeout 100ms |
| Memory     | Redis                           | Lịch sử hội thoại, sliding window 10 turns         |
| Barge-in   | asyncio.Task cancel             | Ngắt lời real-time, không block pipeline           |

---

## 7. Thiết Bị IoT Được Hỗ Trợ

| Function              | Thiết bị                    | Tham số                                                                       |
| --------------------- | --------------------------- | ----------------------------------------------------------------------------- |
| `control_light`       | Đèn thông minh (ESP32)      | `device_id`, `power` ON/OFF, `brightness` 0–100, `color_temp` Kelvin          |
| `control_ac`          | Điều hòa (ESP32)            | `device_id`, `power` ON/OFF, `temperature` 16–30°C, `mode` COOL/HEAT/FAN/AUTO |
| `control_lock`        | Khóa cửa thông minh (ESP32) | `device_id`, `action` LOCK/UNLOCK                                             |
| `query_device_status` | Bất kỳ thiết bị             | `device_id`                                                                   |

---

## 8. LLM Provider Được Hỗ Trợ

| Provider               | Env Var              | Model mặc định                                   |
| ---------------------- | -------------------- | ------------------------------------------------ |
| **Gemini** _(default)_ | `GEMINI_API_KEY`     | `gemini-1.5-flash`                               |
| **OpenAI**             | `OPENAI_API_KEY`     | `gpt-4o-mini`                                    |
| **OpenRouter**         | `OPENROUTER_API_KEY` | `meta-llama/llama-3.1-8b-instruct:free`          |
| **Grok (xAI)**         | `XAI_API_KEY`        | `grok-3-mini`                                    |
| **Together AI**        | `TOGETHER_API_KEY`   | `meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo` |
| **DeepSeek**           | `DEEPSEEK_API_KEY`   | `deepseek-chat`                                  |
| **HuggingFace**        | `HF_API_KEY`         | `meta-llama/Llama-3.1-8B-Instruct`               |

> Chọn provider qua biến môi trường: `LLM_PROVIDER=gemini`
