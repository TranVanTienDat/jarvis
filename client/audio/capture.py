"""
Audio capture module — continuous microphone stream via sounddevice.
Pushes 30ms PCM frames (480 samples @ 16kHz) into an asyncio.Queue.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np
import sounddevice as sd

from client.config import CHANNELS, DTYPE, FRAME_DURATION_MS, SAMPLE_RATE

logger = logging.getLogger(__name__)

# Number of samples per 30ms frame
FRAME_SAMPLES: int = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480


class AudioCaptureError(Exception):
    """Raised when the microphone cannot be opened or read."""


class AudioCapture:
    """Non-blocking microphone capture.

    Usage::

        capture = AudioCapture()
        await capture.start()
        queue = capture.get_frame_queue()
        frame_bytes: bytes = await queue.get()   # 480 int16 samples
        await capture.stop()
    """

    def __init__(self, maxsize: int = 100) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=maxsize)
        self._stream: Optional[sd.InputStream] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the microphone stream and begin pushing frames to the queue."""
        self._loop = asyncio.get_running_loop()
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SAMPLES,
                callback=self._callback,
            )
            self._stream.start()
            logger.info(
                "AudioCapture started: %dHz, %dch, %s, %d samples/frame",
                SAMPLE_RATE,
                CHANNELS,
                DTYPE,
                FRAME_SAMPLES,
            )
        except Exception as exc:
            logger.error("Failed to open microphone: %s", exc)
            raise AudioCaptureError(f"Cannot open microphone: {exc}") from exc

    async def stop(self) -> None:
        """Stop the microphone stream and release resources."""
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
            logger.info("AudioCapture stopped.")

    def get_frame_queue(self) -> asyncio.Queue[bytes]:
        """Return the queue that receives raw PCM frame bytes."""
        return self._queue

    # ------------------------------------------------------------------
    # Internal callback (called from sounddevice audio thread)
    # ------------------------------------------------------------------

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.warning("AudioCapture callback status: %s", status)

        # indata shape: (FRAME_SAMPLES, CHANNELS) dtype int16
        frame_bytes: bytes = indata[:, 0].tobytes()

        if self._loop is not None and not self._loop.is_closed():
            try:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, frame_bytes)
            except asyncio.QueueFull:
                logger.debug("AudioCapture queue full — dropping frame.")
