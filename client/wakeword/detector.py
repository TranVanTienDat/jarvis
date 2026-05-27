"""
Wake word detection using openWakeWord (free, offline, no API key needed).
Uses pre-trained models bundled with the library.
"""
from __future__ import annotations

import logging
import numpy as np

logger = logging.getLogger(__name__)


class WakeWordInitError(Exception):
    """Raised when openWakeWord cannot be initialised."""


class WakeWordDetector:
    """Detects a wake word using openWakeWord.

    Processes 80ms frames (1280 samples at 16kHz).
    Returns True when the model confidence exceeds the threshold.

    Usage::

        detector = WakeWordDetector(model_name="hey_jarvis", threshold=0.5)
        # In the audio loop (IDLE state only):
        pcm_frame: list[int] = [...]   # 1280 int16 samples
        if detector.process(pcm_frame):
            # Wake word detected!
        detector.delete()
    """

    # openWakeWord expects 80ms chunks at 16kHz = 1280 samples
    FRAME_LENGTH: int = 1280

    def __init__(
        self,
        model_name: str = "hey_jarvis",
        threshold: float = 0.5,
    ) -> None:
        """Initialise openWakeWord with the given model.

        Args:
            model_name: Name of the pre-trained model to use.
                        Available: "hey_jarvis", "alexa", "hey_mycroft",
                                   "hey_rhasspy", "current_time", "timer"
            threshold:  Confidence threshold (0.0–1.0). Higher = less sensitive.

        Raises:
            WakeWordInitError: if openWakeWord cannot be loaded.
        """
        try:
            from openwakeword.model import Model  # type: ignore[import]

            self._model = Model(
                wakeword_models=[model_name],
                inference_framework="onnx",
            )
            self._model_name = model_name
            self._threshold = threshold
            self._buffer: list[int] = []
            logger.info(
                "WakeWordDetector initialised. Model: %s, threshold: %.2f",
                model_name,
                threshold,
            )
        except Exception as exc:
            logger.critical("WakeWordDetector init failed: %s", exc)
            raise WakeWordInitError(
                f"Cannot initialise openWakeWord: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def frame_length(self) -> int:
        """Number of int16 samples expected per call to process()."""
        return self.FRAME_LENGTH

    def process(self, pcm_frame: list[int]) -> bool:
        """Process one PCM frame and return True if the wake word is detected.

        Args:
            pcm_frame: list of int16 samples.

        Returns:
            True if wake word was detected, False otherwise.
        """
        try:
            # openWakeWord expects float32 numpy array normalised to [-1, 1]
            audio = np.array(pcm_frame, dtype=np.int16).astype(np.float32) / 32768.0

            prediction = self._model.predict(audio)

            score = prediction.get(self._model_name, 0.0)
            if score >= self._threshold:
                logger.info(
                    "Wake word '%s' detected! (confidence: %.3f)",
                    self._model_name,
                    score,
                )
                # Reset model state after detection to avoid repeated triggers
                self._model.reset()
                return True
            return False

        except Exception as exc:
            logger.warning("WakeWordDetector.process error: %s", exc)
            return False

    def delete(self) -> None:
        """Release resources. Call when shutting down."""
        logger.info("WakeWordDetector released.")
