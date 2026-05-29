"""
Local STT engine using UsefulSensors/moonshine-tiny-vi.
Streams tokens via TextIteratorStreamer as they are decoded.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Thread
from typing import AsyncIterator, Optional

import numpy as np
import torch
from transformers import AutoProcessor, MoonshineForConditionalGeneration, TextIteratorStreamer
import os

from client.config import SAMPLE_RATE, STT_MODEL_ID

logger = logging.getLogger(__name__)

# token_limit_factor prevents hallucination loops (from model card)
_TOKEN_LIMIT_FACTOR: float = 13.0 / SAMPLE_RATE


class STTError(Exception):
    """Raised when the STT engine encounters an unrecoverable error."""


class STTEngine:
    """Local Vietnamese STT using moonshine-tiny-vi.

    Loads the model once at init and reuses it for all transcription calls.
    Uses TextIteratorStreamer so tokens are yielded as they are decoded,
    without waiting for the full transcript.
    """

    def __init__(self) -> None:
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stt")
        self._processor: Optional[AutoProcessor] = None
        self._model: Optional[MoonshineForConditionalGeneration] = None

    async def load(self) -> None:
        """Load the model (call once at startup, runs in executor)."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._load_sync)

    def _load_sync(self) -> None:
        logger.info("Loading STT model: %s on %s …", STT_MODEL_ID, self._device)
        # Respect common HF cache env vars, fallback to project-local cache
        cache_dir = os.environ.get("TRANSFORMERS_CACHE") or os.environ.get("HF_HOME") or "./.cache/huggingface"
        self._processor = AutoProcessor.from_pretrained(STT_MODEL_ID, cache_dir=cache_dir)
        self._model = MoonshineForConditionalGeneration.from_pretrained(
            STT_MODEL_ID, cache_dir=cache_dir, torch_dtype=self._dtype
        ).to(self._device)
        self._model.eval()
        logger.info("STT model loaded.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def transcribe_stream(self, audio_frames: list[bytes]) -> AsyncIterator[str]:
        """Yield tokens as they are decoded by the model.

        Args:
            audio_frames: list of raw int16 PCM byte frames (30ms each).

        Yields:
            Decoded token strings, one at a time.

        Raises:
            STTError: on inference failure.
        """
        if self._model is None or self._processor is None:
            raise STTError("STT model not loaded. Call load() first.")

        audio_np = self._frames_to_float32(audio_frames)
        inputs = self._prepare_inputs(audio_np)
        max_length = self._compute_max_length(inputs)

        streamer = TextIteratorStreamer(
            self._processor.tokenizer,
            skip_special_tokens=True,
            skip_prompt=True,
        )

        generate_kwargs = {
            **inputs,
            "streamer": streamer,
            "max_length": max_length,
        }

        # Run generate() in a background thread so it doesn't block the event loop
        error_holder: list[Exception] = []

        def _generate() -> None:
            try:
                with torch.no_grad():
                    self._model.generate(**generate_kwargs)
            except Exception as exc:
                error_holder.append(exc)

        thread = Thread(target=_generate, daemon=True)
        thread.start()

        loop = asyncio.get_running_loop()

        # Stream tokens from the streamer (blocking iteration in executor)
        token_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        def _drain_streamer() -> None:
            try:
                for token in streamer:
                    loop.call_soon_threadsafe(token_queue.put_nowait, token)
            finally:
                loop.call_soon_threadsafe(token_queue.put_nowait, None)  # sentinel

        drain_thread = Thread(target=_drain_streamer, daemon=True)
        drain_thread.start()

        while True:
            token = await token_queue.get()
            if token is None:
                break
            if token:
                yield token

        thread.join()
        drain_thread.join()

        if error_holder:
            raise STTError(f"STT inference error: {error_holder[0]}") from error_holder[0]

    async def transcribe_final(self, audio_frames: list[bytes]) -> str:
        """Return the complete transcript as a single string.

        Internally calls transcribe_stream and joins all tokens.
        """
        tokens: list[str] = []
        async for token in self.transcribe_stream(audio_frames):
            tokens.append(token)
        return "".join(tokens).strip()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _frames_to_float32(audio_frames: list[bytes]) -> np.ndarray:
        """Concatenate int16 PCM frames and normalise to float32 [-1, 1]."""
        raw = b"".join(audio_frames)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        return samples / 32768.0

    def _prepare_inputs(self, audio_np: np.ndarray) -> dict:
        inputs = self._processor(
            audio_np,
            sampling_rate=SAMPLE_RATE,
            return_tensors="pt",
        )
        return {k: v.to(self._device, self._dtype) for k, v in inputs.items()}

    @staticmethod
    def _compute_max_length(inputs: dict) -> int:
        """Compute max generation length to prevent hallucination loops."""
        seq_lens = inputs["attention_mask"].sum(dim=-1)
        max_len = int((seq_lens * _TOKEN_LIMIT_FACTOR).max().item())
        return max(10, max_len)
