"""
Server configuration — environment variables with sensible defaults.
Secrets (GEMINI_API_KEY) must be set in the environment or .env file.
"""
import os

# ─── Server ───────────────────────────────────────────────────────────────────
HOST: str = os.environ.get("HOST", "0.0.0.0")
PORT: int = int(os.environ.get("PORT", "8000"))

# ─── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379")
SESSION_HISTORY_MAX: int = 10  # sliding window — max conversation turns kept

# ─── LLM (Gemini) ─────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# ─── TTS (Edge-TTS) ───────────────────────────────────────────────────────────
TTS_VOICE: str = os.environ.get("TTS_VOICE", "vi-VN-HoaiMyNeural")
TTS_CHUNK_SIZE_MS: int = 80  # target audio chunk duration in ms

# ─── MQTT ─────────────────────────────────────────────────────────────────────
MQTT_BROKER_HOST: str = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT: int = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_COMMAND_TIMEOUT_S: float = 0.1  # 100 ms — IoT device response deadline

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
