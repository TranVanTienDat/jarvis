"""
Central Orchestrator — coordinates the full server-side pipeline.

Pipeline per final_transcript:
  1. StateManager: LISTENING → PROCESSING
  2. ContextManager: load history
  3. IntentClassifier: classify intent
  4. PolicyEngine: route to ToolManager or LLM
  5. LLMService: stream tokens
  6. TTSService: synthesise audio chunks
  7. WebSocket: send audio_chunk messages
  8. StateManager: PROCESSING → SPEAKING → IDLE
  9. ContextManager: save turn

Barge-in: cancel active LLM/TTS task, send clear_buffer, → LISTENING.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Dict, Optional

from fastapi import WebSocket

from server.models.schemas import (
    AudioChunkMsg,
    ClearBufferMsg,
    ErrorMsg,
    StateChangeMsg,
)
from server.orchestrator.context_manager import ContextManager
from server.orchestrator.intent_classifier import IntentClassifier
from server.orchestrator.policy_engine import PolicyEngine
from server.orchestrator.state_manager import State, StateManager
from server.orchestrator.tool_manager import ToolManager
from server.llms.base import BaseLLMService, LLMError
from server.services.tts import TTSError, TTSService

logger = logging.getLogger(__name__)


class Orchestrator:
    """Central coordinator for the voice chatbot server pipeline."""

    def __init__(
        self,
        context_manager: ContextManager,
        intent_classifier: IntentClassifier,
        policy_engine: PolicyEngine,
        state_manager: StateManager,
        tool_manager: ToolManager,
        llm_service: BaseLLMService,
        tts_service: TTSService,
    ) -> None:
        self.context_manager = context_manager
        self.intent_classifier = intent_classifier
        self.policy_engine = policy_engine
        self.state_manager = state_manager
        self.tool_manager = tool_manager
        self.llm_service = llm_service
        self.tts_service = tts_service

        # Active asyncio tasks per session (for barge-in cancellation)
        self._active_tasks: Dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_final_transcript(
        self,
        session_id: str,
        text: str,
        websocket: WebSocket,
    ) -> None:
        """Process a final transcript through the full pipeline."""
        t0 = time.monotonic()

        # LISTENING → PROCESSING
        await self.state_manager.transition(session_id, State.PROCESSING)
        await self._send(websocket, StateChangeMsg(event="state_change", state="PROCESSING"))

        # Create and register the pipeline task so it can be cancelled on barge-in
        task = asyncio.create_task(
            self._pipeline(session_id, text, websocket, t0)
        )
        self._register_task(session_id, task)

        try:
            await task
        except asyncio.CancelledError:
            logger.info("[%s] Pipeline task cancelled (barge-in).", session_id)
        except Exception as exc:
            logger.error("[%s] Pipeline error: %s", session_id, exc)
            await self._send(
                websocket,
                ErrorMsg(event="error", code="PIPELINE_ERROR", message=str(exc)),
            )
            await self.state_manager.transition(session_id, State.ERROR)

    async def handle_barge_in(
        self,
        session_id: str,
        websocket: WebSocket,
    ) -> None:
        """Cancel active pipeline and return to LISTENING state."""
        logger.info("[%s] Barge-in received — cancelling active task.", session_id)
        await self._cancel_task(session_id)

        await self._send(websocket, ClearBufferMsg(event="clear_buffer"))
        await self.state_manager.transition(session_id, State.LISTENING)
        await self._send(websocket, StateChangeMsg(event="state_change", state="LISTENING"))

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    async def _pipeline(
        self,
        session_id: str,
        text: str,
        websocket: WebSocket,
        t0: float,
    ) -> None:
        """Full pipeline: context → intent → policy → LLM → TTS → audio."""

        # 1. Load conversation history
        history = await self.context_manager.get_history(session_id)

        # 2. Classify intent
        intent = await self.intent_classifier.classify(text, history)

        # 3. Policy routing
        policy_result = await self.policy_engine.execute(
            intent=intent,
            session_id=session_id,
            history=history,
            current_text=text,
        )

        t1 = time.monotonic()
        logger.debug("[%s] Intent+Policy: %.0fms", session_id, (t1 - t0) * 1000)

        # 4. LLM streaming → TTS streaming → send audio chunks
        await self.state_manager.transition(session_id, State.SPEAKING)
        await self._send(websocket, StateChangeMsg(event="state_change", state="SPEAKING"))

        seq = 0
        full_response = ""

        try:
            # Inject websocket for FallbackChain TTS notifications (duck typing)
            if hasattr(self.llm_service, "set_websocket"):
                self.llm_service.set_websocket(websocket)

            token_stream = self.llm_service.stream(policy_result.llm_context)
            audio_stream = self.tts_service.synthesize_stream(token_stream)

            t2 = time.monotonic()

            async for audio_chunk in audio_stream:
                if not audio_chunk:
                    continue

                encoded = base64.b64encode(audio_chunk).decode("ascii")
                await self._send(
                    websocket,
                    AudioChunkMsg(event="audio_chunk", data=encoded, seq=seq),
                )
                seq += 1

                if seq == 1:
                    t3 = time.monotonic()
                    logger.info(
                        "[%s] Latency — policy: %.0fms, first_audio: %.0fms, total: %.0fms",
                        session_id,
                        (t1 - t0) * 1000,
                        (t3 - t2) * 1000,
                        (t3 - t0) * 1000,
                    )

        except (LLMError, TTSError) as exc:
            logger.error("[%s] LLM/TTS error: %s", session_id, exc)
            code = "LLM_ERROR" if isinstance(exc, LLMError) else "TTS_ERROR"
            await self._send(websocket, ErrorMsg(event="error", code=code, message=str(exc)))
            await self.state_manager.transition(session_id, State.ERROR)
            return

        # 5. Save turn to context
        await self.context_manager.add_message(session_id, "user", text)
        # Note: full_response would need to be collected from token stream
        # For now we save a placeholder; a production impl would buffer tokens

        # 6. Return to IDLE
        await self.state_manager.transition(session_id, State.IDLE)
        await self._send(websocket, StateChangeMsg(event="state_change", state="IDLE"))

    # ------------------------------------------------------------------
    # Task management
    # ------------------------------------------------------------------

    def _register_task(self, session_id: str, task: asyncio.Task) -> None:
        """Store a reference to the active pipeline task."""
        old = self._active_tasks.get(session_id)
        if old and not old.done():
            old.cancel()
        self._active_tasks[session_id] = task

    async def _cancel_task(self, session_id: str) -> None:
        """Cancel and await the active pipeline task for a session."""
        task = self._active_tasks.pop(session_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _send(websocket: WebSocket, msg) -> None:
        """Serialise a Pydantic message and send over WebSocket."""
        try:
            await websocket.send_text(msg.model_dump_json())
        except Exception as exc:
            logger.warning("WebSocket send error: %s", exc)
