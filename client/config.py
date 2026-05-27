"""
Client configuration — constants and environment variables.
All values can be overridden via environment variables.
"""
import os

# ─── Audio ────────────────────────────────────────────────────────────────────
SAMPLE_RATE: int = 16_000          # 16 kHz
FRAME_DURATION_MS: int = 30        # 30 ms → 480 samples per frame
CHANNELS: int = 1                  # Mono
DTYPE: str = "int16"

# ─── VAD ──────────────────────────────────────────────────────────────────────
VAD_AGGRESSIVENESS: int = 2                  # 0–3; 2 = balanced sensitivity
SILENCE_THRESHOLD_FRAMES: int = 17          # 17 × 30 ms ≈ 510 ms → end-of-utterance
BARGE_IN_MIN_FRAMES: int = 5               # 5 × 30 ms = 150 ms → barge-in trigger
SPEAKER_ACTIVE_MULTIPLIER: float = 2.5     # dynamic energy threshold multiplier

# ─── Wake Word (openWakeWord) ─────────────────────────────────────────────────
# Available models: hey_jarvis, alexa, hey_mycroft, hey_rhasspy
WAKEWORD_MODEL: str = os.environ.get("WAKEWORD_MODEL", "hey_jarvis")
WAKEWORD_THRESHOLD: float = float(os.environ.get("WAKEWORD_THRESHOLD", "0.5"))

# ─── STT ──────────────────────────────────────────────────────────────────────
STT_MODEL_ID: str = "UsefulSensors/moonshine-tiny-vi"

# ─── Transport ────────────────────────────────────────────────────────────────
SERVER_URI: str = os.environ.get("SERVER_URI", "ws://localhost:8000/ws/chat")
WS_MAX_RETRIES: int = 5
WS_MAX_BACKOFF_S: int = 60  # cap for exponential backoff delay
