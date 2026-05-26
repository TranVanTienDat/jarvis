"""
Audio playback module — streams TTS audio chunks to the speaker via sounddevice.
Supports immediate stop for barge-in (< 200ms).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import numpy as np
import sounddevice as sd

from client.config import CHANNELS, SAMPLE_RATE

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Plays PCM audio chunks received from the server.

    Chunks are enqueued via play_chunk() and consumed by a background
    asyncio task that writes to a sounddevice OutputStream.
    stop() clears the queue immediately to support barge-in.
    """

    _SENTINEL = b""  # signals the playback loop to stop

    def __init__(self) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._playing: bool = False
        self._stream: Optional[sd.OutputStream] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background playback loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._playback_loop())
            logger.debug("AudioPlayer playback loop started.")

    async def stop(self) -> None:
        """Stop playback immediately and clear the audio buffer (barge-in)."""
        # Drain the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Signal the loop to exit
        await self._queue.put(self._SENTINEL)
        self._playing = False

        # Stop sounddevice stream if open
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        logger.debug("AudioPlayer stopped and buffer cleared.")

    async def play_chunk(self, chunk: bytes) -> None:
        """Enqueue a PCM audio chunk for playback."""
        await self._queue.put(chunk)
        self._playing = True

    @property
    def is_playing(self) -> bool:
        """True while there are chunks in the queue or audio is being output."""
        return self._playing and not self._queue.empty()

    # ------------------------------------------------------------------
    # Internal playback loop
    # ------------------------------------------------------------------

    async def _playback_loop(self) -> None:
        """Consume chunks from the queue and play them via sounddevice."""
        loop = asyncio.get_running_loop()

        while True:
            chunk = await self._queue.get()

            if chunk == self._SENTINEL:
                self._playing = False
                break

            if not chunk:
                continue

            try:
                # Convert int16 bytes → float32 for sounddevice
                pcm = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0

                # Play synchronously in executor to avoid blocking event loop
                await loop.run_in_executor(
                    None,
                    lambda p=pcm: sd.play(p, samplerate=SAMPLE_RATE, blocking=True),
                )
            except Exception as exc:
                logger.warning("AudioPlayer playback error: %s", exc)

            if self._queue.empty():
                self._playing = False
