"""
TTS service — Edge-TTS streaming for Vietnamese.
Buffers LLM tokens at sentence boundaries before synthesising,
then yields PCM audio chunks.
"""
from __future__ import annotations

import asyncio
import io
import logging
from typing import AsyncIterator

import edge_tts

from server.config import TTS_CHUNK_SIZE_MS, TTS_VOICE

logger = logging.getLogger(__name__)

# Sentence boundary characters — flush buffer when encountered
_SENTENCE_ENDS = frozenset(".!?。！？…\n")
_MAX_BUFFER_CHARS = 50   # also flush when buffer exceeds this length

# PCM parameters matching client expectations
_SAMPLE_RATE = 16_000
_BYTES_PER_SAMPLE = 2    # int16
_CHUNK_BYTES = int(_SAMPLE_RATE * TTS_CHUNK_SIZE_MS / 1000) * _BYTES_PER_SAMPLE


class TTSError(Exception):
    """Raised when Edge-TTS synthesis fails."""


class TTSService:
    """Streams audio chunks synthesised from a token stream.

    Tokens are buffered until a sentence boundary or MAX_BUFFER_CHARS is
    reached, then the buffer is sent to Edge-TTS and the resulting audio
    is yielded in CHUNK_BYTES-sized pieces.

    Usage::

        tts = TTSService()
        async for audio_chunk in tts.synthesize_stream(token_stream):
            await websocket.send_bytes(audio_chunk)
    """

    def __init__(self, voice: str = TTS_VOICE) -> None:
        self._voice = voice

    async def synthesize_stream(
        self, token_stream: AsyncIterator[str]
    ) -> AsyncIterator[bytes]:
        """Yield PCM audio chunks from a stream of text tokens.

        Raises:
            TTSError: if Edge-TTS synthesis fails.
        """
        buffer = ""

        async for token in token_stream:
            buffer += token

            should_flush = (
                any(ch in _SENTENCE_ENDS for ch in buffer)
                or len(buffer) >= _MAX_BUFFER_CHARS
            )

            if should_flush and buffer.strip():
                async for chunk in self._synthesize_text(buffer.strip()):
                    yield chunk
                buffer = ""

        # Flush remaining buffer
        if buffer.strip():
            async for chunk in self._synthesize_text(buffer.strip()):
                yield chunk

    async def synthesize_text(self, text: str) -> AsyncIterator[bytes]:
        """Synthesise a complete text string and yield audio chunks."""
        async for chunk in self._synthesize_text(text):
            yield chunk

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _synthesize_text(self, text: str) -> AsyncIterator[bytes]:
        """Call Edge-TTS and yield raw audio bytes in chunks."""
        try:
            communicate = edge_tts.Communicate(text, self._voice)
            audio_buffer = io.BytesIO()

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.write(chunk["data"])

            audio_bytes = audio_buffer.getvalue()
            if not audio_bytes:
                return

            # Yield in fixed-size chunks
            offset = 0
            while offset < len(audio_bytes):
                yield audio_bytes[offset: offset + _CHUNK_BYTES]
                offset += _CHUNK_BYTES

        except Exception as exc:
            logger.error("TTSService synthesis error: %s", exc)
            raise TTSError(f"Edge-TTS error: {exc}") from exc
