"""
FallbackNotifier — sends non-blocking TTS audio notifications when
an LLM provider fallback occurs.

Wraps TTSService to synthesize a short Vietnamese message and stream
the resulting audio chunks over the active WebSocket connection.
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

from fastapi import WebSocket

from server.models.schemas import AudioChunkMsg
from server.services.tts import TTSService

logger = logging.getLogger("server.fallback")

# Friendly display names for each provider key
PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "gemini":      "Gemini",
    "deepseek":    "DeepSeek",
    "grok":        "Grok",
    "openrouter":  "OpenRouter",
    "openai":      "OpenAI",
    "together":    "Together",
    "huggingface": "HuggingFace",
}

_TTS_TIMEOUT_S = 5.0  # max seconds to wait for a TTS notification task


class FallbackNotifier:
    """Sends non-blocking TTS audio notifications on provider fallback.

    Usage::

        notifier = FallbackNotifier(tts_service)
        await notifier.notify_fallback("gemini", "deepseek", "đã hết token", ws)
        await notifier.notify_all_failed(ws)
    """

    def __init__(self, tts_service: TTSService) -> None:
        self._tts = tts_service
        self._active_task: Optional[asyncio.Task] = None

    async def notify_fallback(
        self,
        from_provider: str,
        to_provider: str,
        reason: str,
        websocket: WebSocket,
    ) -> None:
        """Fire-and-forget TTS notification when falling back to next provider.

        Cancels any in-progress notification before starting a new one.
        """
        from_name = PROVIDER_DISPLAY_NAMES.get(from_provider, from_provider.capitalize())
        to_name = PROVIDER_DISPLAY_NAMES.get(to_provider, to_provider.capitalize())
        message = f"{from_name} đã {reason}, tôi đang chuyển sang sử dụng {to_name}"
        self._fire(message, websocket)

    async def notify_all_failed(self, websocket: WebSocket) -> None:
        """Fire-and-forget TTS notification when all providers have failed."""
        message = "Tất cả các dịch vụ AI đều không khả dụng, vui lòng thử lại sau"
        self._fire(message, websocket)

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _fire(self, message: str, websocket: WebSocket) -> None:
        """Cancel previous task (if any) and schedule a new TTS task."""
        if self._active_task and not self._active_task.done():
            self._active_task.cancel()
        self._active_task = asyncio.create_task(
            self._speak(message, websocket)
        )

    async def _speak(self, message: str, websocket: WebSocket) -> None:
        """Synthesize message and send audio chunks over websocket."""
        try:
            seq = 0

            async def _stream() -> None:
                nonlocal seq
                async for audio_chunk in self._tts.synthesize_text(message):
                    if not audio_chunk:
                        continue
                    encoded = base64.b64encode(audio_chunk).decode("ascii")
                    try:
                        await websocket.send_text(
                            AudioChunkMsg(
                                event="audio_chunk",
                                data=encoded,
                                seq=seq,
                            ).model_dump_json()
                        )
                        seq += 1
                    except Exception as ws_exc:
                        logger.warning(
                            "FallbackNotifier: WebSocket send error: %s", ws_exc
                        )
                        return

            await asyncio.wait_for(_stream(), timeout=_TTS_TIMEOUT_S)

        except asyncio.CancelledError:
            pass  # cancelled by a newer notification — expected
        except asyncio.TimeoutError:
            logger.warning(
                "FallbackNotifier: TTS notification timed out after %.1fs", _TTS_TIMEOUT_S
            )
        except Exception as exc:
            logger.warning("FallbackNotifier: TTS error: %s", exc)
