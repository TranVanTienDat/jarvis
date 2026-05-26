"""
Wake word detection module using Picovoice Porcupine.
Detects the "Hey AI" keyword from a stream of PCM frames.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class WakeWordInitError(Exception):
    """Raised when Porcupine cannot be initialised."""


class WakeWordDetector:
    """Detects the 'Hey AI' wake word using pvporcupine.

    Usage::

        detector = WakeWordDetector(access_key="...", keyword_path="hey_ai.ppn")
        # In the audio loop (IDLE state only):
        pcm_frame: list[int] = [...]   # 512 int16 samples (Porcupine frame size)
        if detector.process(pcm_frame):
            # Wake word detected!
        detector.delete()
    """

    def __init__(self, access_key: str, keyword_path: str) -> None:
        """Initialise Porcupine with the given access key and keyword model.

        Raises:
            WakeWordInitError: if Porcupine cannot be loaded (bad key, missing
                               model file, unsupported platform, etc.).
        """
        try:
            import pvporcupine  # type: ignore[import]

            self._porcupine = pvporcupine.create(
                access_key=access_key,
                keyword_paths=[keyword_path],
            )
            self._frame_length: int = self._porcupine.frame_length
            logger.info(
                "WakeWordDetector initialised. Frame length: %d samples.",
                self._frame_length,
            )
        except Exception as exc:
            logger.critical("WakeWordDetector init failed: %s", exc)
            raise WakeWordInitError(
                f"Cannot initialise Porcupine wake word detector: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def frame_length(self) -> int:
        """Number of int16 samples expected per call to process()."""
        return self._frame_length

    def process(self, pcm_frame: list[int]) -> bool:
        """Process one PCM frame and return True if the wake word is detected.

        Args:
            pcm_frame: list of int16 samples, length must equal frame_length.

        Returns:
            True if 'Hey AI' was detected in this frame, False otherwise.
        """
        try:
            result = self._porcupine.process(pcm_frame)
            return result >= 0  # >= 0 means a keyword was detected
        except Exception as exc:
            logger.warning("WakeWordDetector.process error: %s", exc)
            return False

    def delete(self) -> None:
        """Release Porcupine resources. Call when shutting down."""
        try:
            self._porcupine.delete()
            logger.info("WakeWordDetector resources released.")
        except Exception as exc:
            logger.warning("WakeWordDetector.delete error: %s", exc)
