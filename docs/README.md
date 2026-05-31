# HỆ THỐNG VOICE CHATBOT IOT THỜI GIAN THỰC - TÀI LIỆU DỰ ÁN

## (Real-time Voice Chatbot IoT Documentation Hub)

![Mô hình kiến trúc thời gian thực](/docs/assets/architecture.png)

Chào mừng Lão đại đến với trung tâm tài liệu kỹ thuật của dự án **Real-time Voice Chatbot IoT**. Tài liệu này được cấu trúc theo dạng modular (chia nhỏ) giúp dễ dàng theo dõi, phát triển và cập nhật từng thành phần của hệ thống.

---

## 🗺️ Bản Đồ Tài Liệu (Document Map)

### 📌 1. Đặc Tả Kỹ Thuật (System Specifications)

- **[Đặc tả Cấu hình Streaming & KPIs](specification/streaming_config.md)**
  - _Chi tiết_: Kích thước audio chunk, khoảng thời gian trễ của STT, LLM, TTS và các chỉ số KPI cam kết (Latency < 500ms, WER, tỷ lệ ngắt lời thành công...).
- **[Lựa chọn Công nghệ & Thư viện (Tech Stack)](specification/tech_stack.md)**
  - _Chi tiết_: Các thư viện Python dùng cho thiết bị IoT (Client) và máy chủ (Server), danh sách các API dịch vụ AI tối ưu nhất cho tiếng Việt.

### 🏗️ 2. Thiết Kế Kiến Trúc & Luồng Dữ Liệu (Architecture & Design)

- **[Luồng xử lý dữ liệu tổng thể (Pipeline Flow)](architecture/pipeline_flow.md)**
  - _Chi tiết_: Sơ đồ khối kiến trúc hệ thống và sơ đồ Sequence luồng dữ liệu thời gian thực từ Microphone đến Loa.
- **[Thiết kế Bộ điều phối trung tâm (Orchestrator)](architecture/orchestrator.md)**
  - _Chi tiết_: Cấu trúc module nội bộ chịu trách nhiệm quản lý ngữ cảnh hội thoại, nhận diện ý định điều khiển (NLU/Intent) và quản lý trạng thái phiên làm việc.
- **[Giải thuật Ngắt lời (Barge-in Logic)](architecture/barge_in.md)**
  - _Chi tiết_: Thiết kế giải thuật VAD cục bộ phía Client và cơ chế hủy tiến trình xử lý bất đồng bộ (asyncio task cancellation) phía Server khi phát hiện nói chen ngang.
- **[Lớp Điều khiển Thiết bị IoT (IoT Control Layer)](architecture/iot_control.md)**
  - _Chi tiết_: Cấu trúc bản tin MQTT để điều khiển thiết bị phần cứng (ESP32/ESP8266) và nhận phản hồi trạng thái về Server.

---

## 🛠️ Hướng Dẫn Phát Triển Nhanh (Quick Start Reference)

Hệ thống sử dụng **Python** làm ngôn ngữ chủ đạo cho cả Client (thiết bị Edge) và Server (FastAPI).

1.  **Thiết lập môi trường**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```
2.  **Khởi động các dịch vụ phụ trợ**:
    - Chạy MQTT Broker (Mosquitto) nội bộ hoặc cloud.
    - Chạy Redis để lưu cache session hội thoại.

## ▶️ Chạy thử cục bộ (Run locally)

Sau khi đã kích hoạt virtualenv và cài dependencies, bạn có thể chạy các lệnh sau để thử STT từ file WAV hoặc khởi chạy client:

- Chạy helper để transcribe một file WAV 16 kHz mono int16:

  `python3 -m client.stt.test_helpers path/to/your_16k_mono.wav`

- Khởi chạy client (phiên local, dùng Python từ virtualenv):

  `.venv/bin/python3 -m client.main`

Ghi chú: lần chạy đầu tiên `STTEngine.load()` có thể mất thời gian (tải model, nạp weights). Nên load model một lần và reuse nếu chạy nhiều lần.
