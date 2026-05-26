"""
Server configuration — environment variables with sensible defaults.
Secrets (API keys) must be set in the environment or .env file.
"""
import os

# ─── Server ───────────────────────────────────────────────────────────────────
HOST: str = os.environ.get("HOST", "0.0.0.0")
PORT: int = int(os.environ.get("PORT", "8000"))

# ─── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379")
SESSION_HISTORY_MAX: int = 10  # sliding window — max conversation turns kept

# ─── LLM — provider selection ─────────────────────────────────────────────────
# Set LLM_PROVIDER to one of: gemini | openai | openrouter | grok | together
LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "gemini")

# ─── LLM — Gemini ─────────────────────────────────────────────────────────────
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

# ─── LLM — OpenAI ─────────────────────────────────────────────────────────────
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ─── LLM — OpenRouter ─────────────────────────────────────────────────────────
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.environ.get(
    "OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free"
)

# ─── LLM — Grok (xAI) ────────────────────────────────────────────────────────
XAI_API_KEY: str = os.environ.get("XAI_API_KEY", "")
GROK_MODEL: str = os.environ.get("GROK_MODEL", "grok-3-mini")

# ─── LLM — Together AI ────────────────────────────────────────────────────────
TOGETHER_API_KEY: str = os.environ.get("TOGETHER_API_KEY", "")
TOGETHER_MODEL: str = os.environ.get(
    "TOGETHER_MODEL", "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo"
)

# ─── TTS (Edge-TTS) ───────────────────────────────────────────────────────────
TTS_VOICE: str = os.environ.get("TTS_VOICE", "vi-VN-HoaiMyNeural")
TTS_CHUNK_SIZE_MS: int = 80  # target audio chunk duration in ms

# ─── MQTT ─────────────────────────────────────────────────────────────────────
MQTT_BROKER_HOST: str = os.environ.get("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT: int = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
MQTT_COMMAND_TIMEOUT_S: float = 0.1  # 100 ms — IoT device response deadline

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
