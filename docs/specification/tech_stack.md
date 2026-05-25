# LỰA CHỌN CÔNG NGHỆ & THƯ VIỆN (TECH STACK)
## (Technology Stack & Libraries)

Tài liệu này đặc tả chi tiết các phần cứng, thư viện phần mềm Python và dịch vụ API được lựa chọn để xây dựng hệ thống Voice Chatbot IoT.

---

## 1. Công Nghệ Phía Client (IoT Edge Device)

Thiết bị Client cần có cấu hình vừa đủ để thu âm, phát âm thanh, xử lý các tác vụ AI cục bộ (VAD, Wake Word) để tiết kiệm băng thông và đảm bảo quyền riêng tư.

### 1.1. Khuyến Nghị Phần Cứng
*   **Thiết bị xử lý chính:** Raspberry Pi 4 Model B (RAM 2GB/4GB) hoặc Raspberry Pi 5.
*   **Đầu vào âm thanh (Audio Input):** Microphone USB đa hướng có tích hợp mạch khử nhiễu (DSP) hoặc board soundcard ReSpeaker 2-Mics Hat.
*   **Đầu ra âm thanh (Audio Output):** Loa cổng 3.5mm, USB Speaker, hoặc kết nối qua HDMI/Bluetooth.

### 1.2. Thư Viện Python Phía Client
*   **`sounddevice` (kết hợp `numpy`):** 
    *   *Mục đích:* Thu phát âm thanh dạng non-blocking stream.
    *   *Lý do chọn:* API dễ dùng hơn `PyAudio`, quản lý buffer tốt trên môi trường Linux (Raspberry Pi OS).
*   **`webrtcvad`:**
    *   *Mục đích:* Phát hiện giọng nói (VAD - Voice Activity Detection).
    *   *Lý do chọn:* Chạy offline hoàn toàn trên CPU ARM của Pi cực kỳ nhanh, thuật toán WebRTC VAD đã được kiểm chứng thực tế về tốc độ và hiệu năng.
*   **`pvporcupine` (Picovoice Porcupine):**
    *   *Mục đích:* Phát hiện từ khóa kích hoạt (Wake Word) như "Hey AI", "Ok Google".
    *   *Lý do chọn:* Tỷ lệ kích hoạt sai (False Alarm) cực thấp, sử dụng tài liệu huấn luyện trực quan, hỗ trợ tối ưu phần cứng ARM.
*   **`websockets` (Asyncio-based):**
    *   *Mục đích:* Duy trì kết nối WebSocket Client bảo mật đến Server để truyền/nhận dòng audio.

---

## 2. Công Nghệ Phía Server (Central Orchestrator)

Server đóng vai trò trung tâm điều phối toàn bộ tài nguyên AI và kết nối thiết bị.

### 2.1. Framework Lập Trình Backend
*   **`FastAPI` & `Uvicorn`:**
    *   *Lý do chọn:* Hỗ trợ lập trình bất đồng bộ (`asyncio`) cực mạnh, tốc độ xử lý request ngang ngửa Go/Node.js, hỗ trợ tự động sinh tài liệu API (Swagger UI) và xử lý WebSocket native rất ổn định.

### 2.2. Dịch Vụ AI & Xử Lý Ngôn Ngữ
*   **Speech-to-Text (STT):**
    *   **Deepgram Streaming API:** Lựa chọn tốt nhất cho streaming thời gian thực, có hỗ trợ tiếng Việt, độ trễ nhận diện thấp nhất (< 150ms), trả về partial result liên tục.
    *   *Giải pháp tự host:* `Faster-Whisper` kết hợp framework streaming tự viết trên server có GPU (NVIDIA T4 trở lên).
*   **Large Language Model (LLM):**
    *   **Gemini 1.5 Flash API:** Sinh token siêu nhanh (Time-to-First-Token cực thấp), hỗ trợ tốt cơ chế gọi hàm (Function Calling) để điều khiển thiết bị IoT, chi phí tối ưu.
    *   **Groq API (Llama 3 70B):** Tốc độ suy luận nhanh nhất thị trường thời điểm hiện tại.
*   **Text-to-Speech (TTS):**
    *   **Edge-TTS (Wrapper Microsoft Edge TTS):** Sinh file audio tiếng Việt tự nhiên, hoàn toàn miễn phí, tốc độ chuyển đổi nhanh.
    *   **ElevenLabs / PlayHT:** Chất lượng giọng đọc cao cấp (gần như người thật), phù hợp cho các dự án thương mại cao cấp, kết nối qua SDK streaming.

### 2.3. Hệ Thống Lưu Trữ & Bộ Nhớ Đệm
*   **`Redis`:**
    *   *Mục đích:* Lưu trữ thông tin trạng thái phiên làm việc (Session state) của người dùng và lưu trữ đệm (buffer) lịch sử hội thoại ngắn hạn.
*   **`PostgreSQL` với `pgvector`:**
    *   *Mục đích:* Cơ sở dữ liệu chính lưu thông tin cấu hình thiết bị và lịch sử hội thoại dài hạn kết hợp Vector Database để làm RAG (Hỏi đáp tài liệu thông minh).

---

## 3. Lớp Giao Tiếp & Điều Khiển Thiết Bị (IoT Control Layer)

*   **Giao thức:** **MQTT (Message Queuing Telemetry Transport)**.
*   **MQTT Broker:** `Mosquitto` (được triển khai bằng Docker trên máy chủ Server hoặc Cloud).
*   **Thư viện Python trên Server:** `paho-mqtt` giúp Server gửi lệnh điều khiển xuống Broker và subscribe nhận trạng thái thiết bị.
*   **Thiết bị phần cứng đầu cuối (IoT Node):**
    *   Vi điều khiển **ESP32** (hoặc ESP8266): Tích hợp sẵn Wi-Fi, rẻ, hiệu năng cao.
    *   Lập trình bằng **C++ (Arduino IDE)** hoặc **MicroPython** sử dụng thư viện MQTT client để lắng nghe kênh điều khiển và điều khiển các thiết bị vật lý qua chân GPIO (rơ-le, cảm biến...).
