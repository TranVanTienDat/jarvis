"""
Voice Activity Detection module.
Wraps webrtcvad and adds end-of-utterance detection and barge-in detection
with dynamic energy thresholding.
"""
from __future__ import annotations

import logging
import struct

import numpy as np
import webrtcvad

from client.config import (
    BARGE_IN_MIN_FRAMES,
    SAMPLE_RATE,
    SILENCE_THRESHOLD_FRAMES,
    SPEAKER_ACTIVE_MULTIPLIER,
    VAD_AGGRESSIVENESS,
)

logger = logging.getLogger(__name__)


class VAD:
    """Voice Activity Detector with end-of-utterance and barge-in support.

    End-of-utterance: fires after SILENCE_THRESHOLD_FRAMES (17 × 30ms ≈ 510ms)
    consecutive silence frames following at least one speech frame.

    Barge-in: fires after BARGE_IN_MIN_FRAMES (5 × 30ms = 150ms) consecutive
    speech frames while speaker_active=True (loa đang phát).
    """

    def __init__(self) -> None:
        self._vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self._silence_count: int = 0
        self._speech_count: int = 0
        self._has_speech: bool = False          # at least one speech frame seen
        self._speaker_active: bool = False      # True when TTS audio is playing
        self._barge_in_count: int = 0           # consecutive speech frames during playback

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_speech(self, frame: bytes, sample_rate: int = SAMPLE_RATE) -> bool:
        """Return True if the frame contains speech (webrtcvad decision)."""
        try:
            return self._vad.is_speech(frame, sample_rate)
        except Exception as exc:
            logger.debug("webrtcvad error: %s", exc)
            return False

    def check_end_of_utterance(self, frame: bytes) -> bool:
        """Process one frame and return True when end-of-utterance is detected.

        End-of-utterance = SILENCE_THRESHOLD_FRAMES consecutive silence frames
        after at least one speech frame has been observed.
        Resets internal counters on trigger.
        """
        speech = self.is_speech(frame)

        if speech:
            self._has_speech = True
            self._silence_count = 0
        else:
            if self._has_speech:
                self._silence_count += 1
                if self._silence_count >= SILENCE_THRESHOLD_FRAMES:
                    # End of utterance detected — reset state
                    self._silence_count = 0
                    self._has_speech = False
                    return True

        return False

    def check_barge_in(self, frame: bytes, speaker_active: bool) -> bool:
        """Return True when barge-in is detected.

        Barge-in = BARGE_IN_MIN_FRAMES consecutive speech frames while
        speaker_active=True.  Uses dynamic energy threshold to avoid false
        triggers from speaker echo.
        """
        if not speaker_active:
            self._barge_in_count = 0
            return False

        # Dynamic energy threshold: require higher energy when speaker is active
        rms = self._rms_energy(frame)
        base_threshold = self._compute_base_threshold(frame)
        effective_threshold = base_threshold * SPEAKER_ACTIVE_MULTIPLIER

        above_threshold = rms > effective_threshold
        webrtc_speech = self.is_speech(frame)

        if above_threshold and webrtc_speech:
            self._barge_in_count += 1
        else:
            self._barge_in_count = 0

        if self._barge_in_count >= BARGE_IN_MIN_FRAMES:
            self._barge_in_count = 0
            return True

        return False

    def set_speaker_active(self, active: bool) -> None:
        """Notify VAD whether the speaker (TTS playback) is currently active."""
        self._speaker_active = active
        if not active:
            self._barge_in_count = 0

    def reset(self) -> None:
        """Reset all internal counters (call when starting a new utterance)."""
        self._silence_count = 0
        self._speech_count = 0
        self._has_speech = False
        self._barge_in_count = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rms_energy(frame: bytes) -> float:
        """Compute RMS energy of a 16-bit PCM frame."""
        if not frame:
            return 0.0
        samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        return float(np.sqrt(np.mean(samples ** 2)))

    @staticmethod
    def _compute_base_threshold(frame: bytes) -> float:
        """A fixed base RMS threshold for speech detection (empirical value)."""
        # ~500 RMS corresponds to quiet speech on a typical USB mic
        return 500.0
