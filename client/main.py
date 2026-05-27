"""
Client entry point — orchestrates the full pipeline state machine.

States:
  IDLE      → WakeWordDetector listens, no data sent to server
  LISTENING → STT streams tokens, sends partial/final transcript
  SPEAKING  → AudioPlayer plays TTS chunks, VAD watches for barge-in
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import signal
import sys
from enum import Enum
from typing import Optional

from client.audio.capture import AudioCapture, AudioCaptureError
from client.audio.player import AudioPlayer
from client.audio.vad import VAD
from client.config import (
    SAMPLE_RATE,
    WAKEWORD_MODEL,
    WAKEWORD_THRESHOLD,
)
from client.stt.engine import STTEngine, STTError
from client.transport.ws_client import ConnectionFailed, WSClient
from client.wakeword.detector import WakeWordDetector, WakeWordInitError

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class ClientState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


class VoiceChatbotClient:
    """Full-duplex voice chatbot client pipeline."""

    def __init__(self) -> None:
        self._state = ClientState.IDLE
        self._capture = AudioCapture()
        self._vad = VAD()
        self._player = AudioPlayer()
        self._stt = STTEngine()
        self._ws = WSClient()
        self._wakeword: Optional[WakeWordDetector] = None

        self._speech_buffer: list[bytes] = []
        self._audio_seq: int = 0
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Initialise all components and start the pipeline."""
        logger.info("Starting VoiceChatbotClient…")

        # Load STT model
        await self._stt.load()

        # Init wake word detector
        try:
            self._wakeword = WakeWordDetector(
                model_name=WAKEWORD_MODEL,
                threshold=WAKEWORD_THRESHOLD,
            )
        except WakeWordInitError as exc:
            logger.critical("Cannot start: %s", exc)
            sys.exit(1)

        # Connect WebSocket
        try:
            await self._ws.connect()
        except ConnectionFailed as exc:
            logger.critical("Cannot connect to server: %s", exc)
            sys.exit(1)

        # Start audio capture and player
        await self._capture.start()
        await self._player.start()

        self._running = True
        logger.info("Pipeline started. Say 'Hey AI' to begin.")

        # Start recv loop in background
        asyncio.create_task(self._recv_loop())

        # Main pipeline loop
        await self._pipeline_loop()

    async def stop(self) -> None:
        """Gracefully shut down all components."""
        self._running = False
        await self._capture.stop()
        await self._player.stop()
        await self._ws.close()
        if self._wakeword:
            self._wakeword.delete()
        logger.info("VoiceChatbotClient stopped.")

    # ------------------------------------------------------------------
    # Main pipeline loop
    # ------------------------------------------------------------------

    async def _pipeline_loop(self) -> None:
        """Read audio frames and dispatch to the correct handler per state."""
        queue = self._capture.get_frame_queue()
        ww_buffer: list[int] = []  # accumulate samples for Porcupine

        while self._running:
            frame: bytes = await queue.get()

            if self._state == ClientState.IDLE:
                await self._handle_idle(frame, ww_buffer)

            elif self._state == ClientState.LISTENING:
                await self._handle_listening(frame)

            elif self._state == ClientState.SPEAKING:
                await self._handle_speaking(frame)

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    async def _handle_idle(self, frame: bytes, ww_buffer: list[int]) -> None:
        """IDLE: accumulate frames for Porcupine, detect wake word."""
        import struct

        # Convert bytes → list[int16] for Porcupine
        n = len(frame) // 2
        samples = list(struct.unpack(f"{n}h", frame))
        ww_buffer.extend(samples)

        if self._wakeword is None:
            return

        frame_len = self._wakeword.frame_length
        while len(ww_buffer) >= frame_len:
            chunk = ww_buffer[:frame_len]
            ww_buffer[:] = ww_buffer[frame_len:]

            if self._wakeword.process(chunk):
                logger.info("Wake word detected! Switching to LISTENING.")
                self._state = ClientState.LISTENING
                self._speech_buffer = []
                self._vad.reset()
                break

    async def _handle_listening(self, frame: bytes) -> None:
        """LISTENING: buffer speech frames, detect end-of-utterance, run STT."""
        self._speech_buffer.append(frame)

        if self._vad.check_end_of_utterance(frame):
            logger.info("End of utterance detected. Running STT…")
            audio_frames = list(self._speech_buffer)
            self._speech_buffer = []

            asyncio.create_task(self._run_stt(audio_frames))

    async def _handle_speaking(self, frame: bytes) -> None:
        """SPEAKING: watch for barge-in while TTS is playing."""
        if self._vad.check_barge_in(frame, speaker_active=True):
            logger.info("Barge-in detected! Stopping playback.")
            await self._player.stop()
            self._vad.set_speaker_active(False)
            await self._ws.send({"event": "barge_in", "timestamp": _now()})
            # Switch to LISTENING immediately
            self._state = ClientState.LISTENING
            self._speech_buffer = [frame]  # include the barge-in frame
            self._vad.reset()

    # ------------------------------------------------------------------
    # STT task
    # ------------------------------------------------------------------

    async def _run_stt(self, audio_frames: list[bytes]) -> None:
        """Run Moonshine STT, stream partial tokens, send final transcript."""
        tokens: list[str] = []
        try:
            async for token in self._stt.transcribe_stream(audio_frames):
                tokens.append(token)
                await self._ws.send({"event": "partial_transcript", "token": token})

            full_text = "".join(tokens).strip()
            if full_text:
                logger.info("Final transcript: %s", full_text)
                await self._ws.send({"event": "final_transcript", "text": full_text})

        except STTError as exc:
            logger.error("STT error: %s", exc)
            await self._ws.send({"event": "stt_error", "message": str(exc)})
            self._state = ClientState.IDLE

    # ------------------------------------------------------------------
    # Server message receiver
    # ------------------------------------------------------------------

    async def _recv_loop(self) -> None:
        """Receive messages from the server and dispatch handlers."""
        while self._running:
            try:
                msg = await self._ws.recv()
                await self._handle_server_message(msg)
            except ConnectionFailed:
                logger.error("Lost connection to server.")
                self._running = False
                break
            except Exception as exc:
                logger.warning("recv_loop error: %s", exc)

    async def _handle_server_message(self, msg: dict) -> None:
        event = msg.get("event")

        if event == "session_init":
            logger.info("Session ID: %s", msg.get("session_id"))

        elif event == "audio_chunk":
            # Decode base64 PCM and enqueue for playback
            raw = base64.b64decode(msg["data"])
            self._state = ClientState.SPEAKING
            self._vad.set_speaker_active(True)
            await self._player.play_chunk(raw)

        elif event == "clear_buffer":
            # Server confirmed barge-in cancellation
            logger.debug("clear_buffer received from server.")
            self._vad.set_speaker_active(False)
            self._state = ClientState.LISTENING
            self._speech_buffer = []
            self._vad.reset()

        elif event == "state_change":
            logger.debug("Server state: %s", msg.get("state"))

        elif event == "error":
            logger.error("Server error [%s]: %s", msg.get("code"), msg.get("message"))
            self._state = ClientState.IDLE


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _now() -> int:
    import time
    return int(time.time())


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

async def main() -> None:
    client = VoiceChatbotClient()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(client.stop()))

    try:
        await client.start()
    except KeyboardInterrupt:
        await client.stop()


if __name__ == "__main__":
    asyncio.run(main())
