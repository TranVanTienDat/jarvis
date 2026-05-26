"""
WebSocket endpoint — /ws/chat
Accepts client connections, assigns session IDs, validates messages,
and dispatches events to the Orchestrator.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from server.models.schemas import (
    BargeInMsg,
    ClientMessage,
    ErrorMsg,
    FinalTranscriptMsg,
    PartialTranscriptMsg,
    SessionInitMsg,
    STTErrorMsg,
)
from server.orchestrator.state_manager import State

if TYPE_CHECKING:
    from server.orchestrator.core import Orchestrator
    from server.orchestrator.state_manager import StateManager

logger = logging.getLogger(__name__)

router = APIRouter()

# Pydantic TypeAdapter for discriminated union parsing
_client_msg_adapter = TypeAdapter(ClientMessage)


class WSHandler:
    """Manages the lifecycle of a single WebSocket session."""

    def __init__(
        self,
        orchestrator: "Orchestrator",
        state_manager: "StateManager",
    ) -> None:
        self._orchestrator = orchestrator
        self._state_manager = state_manager

    async def handle(self, websocket: WebSocket) -> None:
        """Accept connection, assign session, run message loop."""
        await websocket.accept()
        session_id = str(uuid.uuid4())

        # Initialise session state
        self._state_manager.init_session(session_id)

        # Send session_init to client
        init_msg = SessionInitMsg(event="session_init", session_id=session_id)
        await websocket.send_text(init_msg.model_dump_json())
        logger.info("[%s] WebSocket session opened.", session_id)

        try:
            await self._message_loop(session_id, websocket)
        except WebSocketDisconnect:
            logger.info("[%s] WebSocket disconnected.", session_id)
        except Exception as exc:
            logger.error("[%s] Unexpected error: %s", session_id, exc)
        finally:
            await self._cleanup(session_id)

    async def _message_loop(self, session_id: str, websocket: WebSocket) -> None:
        """Receive and dispatch messages until the connection closes."""
        while True:
            raw = await websocket.receive_text()
            await self._dispatch(session_id, raw, websocket)

    async def _dispatch(
        self,
        session_id: str,
        raw: str,
        websocket: WebSocket,
    ) -> None:
        """Parse and route a raw JSON message."""
        # Validate JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await self._send_error(websocket, "INVALID_PAYLOAD", "Invalid JSON.")
            return

        # Validate schema
        try:
            msg = _client_msg_adapter.validate_python(data)
        except ValidationError as exc:
            logger.warning("[%s] Invalid payload: %s", session_id, exc)
            await self._send_error(websocket, "INVALID_PAYLOAD", str(exc))
            return  # keep connection open

        # Dispatch by event type
        if isinstance(msg, FinalTranscriptMsg):
            logger.info("[%s] final_transcript: %s", session_id, msg.text[:80])
            await self._orchestrator.handle_final_transcript(
                session_id, msg.text, websocket
            )

        elif isinstance(msg, BargeInMsg):
            logger.info("[%s] barge_in at ts=%d", session_id, msg.timestamp)
            await self._orchestrator.handle_barge_in(session_id, websocket)

        elif isinstance(msg, PartialTranscriptMsg):
            # Partial tokens are informational — log at DEBUG only
            logger.debug("[%s] partial: %s", session_id, msg.token)

        elif isinstance(msg, STTErrorMsg):
            logger.warning("[%s] stt_error: %s", session_id, msg.message)
            await self._orchestrator.state_manager.transition(session_id, State.IDLE)

    async def _cleanup(self, session_id: str) -> None:
        """Release session resources on disconnect."""
        await self._orchestrator.handle_barge_in.__func__  # cancel any active task
        try:
            await self._orchestrator._cancel_task(session_id)
        except Exception:
            pass
        await self._orchestrator.context_manager.clear_session(session_id)
        self._state_manager.cleanup_session(session_id)
        logger.info("[%s] Session cleaned up.", session_id)

    @staticmethod
    async def _send_error(
        websocket: WebSocket, code: str, message: str
    ) -> None:
        """Send an error message without closing the connection."""
        try:
            err = ErrorMsg(event="error", code=code, message=message)
            await websocket.send_text(err.model_dump_json())
        except Exception:
            pass


def make_router(orchestrator: "Orchestrator", state_manager: "StateManager") -> APIRouter:
    """Create and return the WebSocket router with injected dependencies."""
    handler = WSHandler(orchestrator=orchestrator, state_manager=state_manager)

    @router.websocket("/ws/chat")
    async def ws_chat(websocket: WebSocket) -> None:
        await handler.handle(websocket)

    return router
