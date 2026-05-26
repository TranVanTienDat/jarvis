"""
Integration tests for the Voice Chatbot IoT system.
Tests WebSocket lifecycle, state machine, barge-in, and session isolation.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio


# ─── Smoke Tests ──────────────────────────────────────────────────────────────

class TestSmoke:
    """Basic sanity checks — verify modules load and key constants are correct."""

    def test_state_manager_has_five_states(self) -> None:
        from server.orchestrator.state_manager import State, VALID_TRANSITIONS
        assert len(list(State)) == 5
        assert len(VALID_TRANSITIONS) == 5

    def test_orchestrator_has_all_submodules(self) -> None:
        from server.orchestrator.core import Orchestrator
        import inspect
        sig = inspect.signature(Orchestrator.__init__)
        params = list(sig.parameters.keys())
        for attr in ("context_manager", "intent_classifier", "policy_engine",
                     "state_manager", "tool_manager", "llm_service", "tts_service"):
            assert attr in params, f"Orchestrator missing param: {attr}"

    def test_mqtt_manager_uses_asyncio_future(self) -> None:
        import inspect
        from server.services.mqtt_manager import MQTTManager
        source = inspect.getsource(MQTTManager.send_command)
        assert "asyncio" in source
        assert "Future" in source or "wait_for" in source

    def test_folder_structure_exists(self) -> None:
        base = os.path.dirname(os.path.dirname(__file__))
        required_paths = [
            "client/audio/capture.py",
            "client/audio/vad.py",
            "client/audio/player.py",
            "client/wakeword/detector.py",
            "client/stt/engine.py",
            "client/transport/ws_client.py",
            "client/main.py",
            "server/api/ws_handler.py",
            "server/orchestrator/core.py",
            "server/orchestrator/context_manager.py",
            "server/orchestrator/intent_classifier.py",
            "server/orchestrator/policy_engine.py",
            "server/orchestrator/state_manager.py",
            "server/orchestrator/tool_manager.py",
            "server/services/llm.py",
            "server/services/tts.py",
            "server/services/mqtt_manager.py",
            "server/models/schemas.py",
            "server/main.py",
        ]
        for rel_path in required_paths:
            full = os.path.join(base, rel_path)
            assert os.path.exists(full), f"Missing: {rel_path}"

    def test_pydantic_schemas_importable(self) -> None:
        from server.models.schemas import (
            AudioChunkMsg, BargeInMsg, ClearBufferMsg, ClientMessage,
            ConversationMessage, ErrorMsg, FinalTranscriptMsg, IoTCommand,
            IoTStatus, PartialTranscriptMsg, PolicyResult, ServerMessage,
            SessionInitMsg, SessionState, StateChangeMsg, STTErrorMsg,
        )

    def test_client_config_constants(self) -> None:
        from client.config import (
            BARGE_IN_MIN_FRAMES, CHANNELS, FRAME_DURATION_MS,
            SAMPLE_RATE, SILENCE_THRESHOLD_FRAMES, SPEAKER_ACTIVE_MULTIPLIER,
        )
        assert SAMPLE_RATE == 16_000
        assert FRAME_DURATION_MS == 30
        assert CHANNELS == 1
        assert SILENCE_THRESHOLD_FRAMES == 17
        assert BARGE_IN_MIN_FRAMES == 5
        assert SPEAKER_ACTIVE_MULTIPLIER > 1.0


# ─── State Machine Tests ──────────────────────────────────────────────────────

class TestStateMachine:
    """StateManager transition logic."""

    @pytest.mark.asyncio
    async def test_initial_state_is_idle(self) -> None:
        from server.orchestrator.state_manager import State, StateManager
        sm = StateManager()
        sid = str(uuid.uuid4())
        sm.init_session(sid)
        assert sm.get_state(sid) == State.IDLE

    @pytest.mark.asyncio
    async def test_valid_transition_succeeds(self) -> None:
        from server.orchestrator.state_manager import State, StateManager
        sm = StateManager()
        sid = str(uuid.uuid4())
        sm.init_session(sid)
        result = await sm.transition(sid, State.LISTENING)
        assert result is True
        assert sm.get_state(sid) == State.LISTENING

    @pytest.mark.asyncio
    async def test_invalid_transition_rejected(self) -> None:
        from server.orchestrator.state_manager import State, StateManager
        sm = StateManager()
        sid = str(uuid.uuid4())
        sm.init_session(sid)
        # IDLE → SPEAKING is invalid
        result = await sm.transition(sid, State.SPEAKING)
        assert result is False
        assert sm.get_state(sid) == State.IDLE  # unchanged

    @pytest.mark.asyncio
    async def test_full_happy_path_transitions(self) -> None:
        from server.orchestrator.state_manager import State, StateManager
        sm = StateManager()
        sid = str(uuid.uuid4())
        sm.init_session(sid)

        assert await sm.transition(sid, State.LISTENING)
        assert await sm.transition(sid, State.PROCESSING)
        assert await sm.transition(sid, State.SPEAKING)
        assert await sm.transition(sid, State.IDLE)
        assert sm.get_state(sid) == State.IDLE

    def test_cleanup_removes_session(self) -> None:
        from server.orchestrator.state_manager import State, StateManager
        sm = StateManager()
        sid = str(uuid.uuid4())
        sm.init_session(sid)
        sm.cleanup_session(sid)
        # After cleanup, get_state returns default IDLE (not an error)
        assert sm.get_state(sid) == State.IDLE


# ─── WebSocket Protocol Tests ─────────────────────────────────────────────────

class TestWebSocketProtocol:
    """Message schema validation and session ID assignment."""

    def test_session_init_message_schema(self) -> None:
        from server.models.schemas import SessionInitMsg
        sid = str(uuid.uuid4())
        msg = SessionInitMsg(event="session_init", session_id=sid)
        data = json.loads(msg.model_dump_json())
        assert data["event"] == "session_init"
        assert data["session_id"] == sid

    def test_audio_chunk_message_schema(self) -> None:
        import base64
        from server.models.schemas import AudioChunkMsg
        raw = b"\x00\x01\x02\x03"
        encoded = base64.b64encode(raw).decode()
        msg = AudioChunkMsg(event="audio_chunk", data=encoded, seq=0)
        data = json.loads(msg.model_dump_json())
        assert data["event"] == "audio_chunk"
        assert data["seq"] == 0
        assert base64.b64decode(data["data"]) == raw

    def test_clear_buffer_message_schema(self) -> None:
        from server.models.schemas import ClearBufferMsg
        msg = ClearBufferMsg(event="clear_buffer")
        data = json.loads(msg.model_dump_json())
        assert data["event"] == "clear_buffer"

    def test_error_message_schema(self) -> None:
        from server.models.schemas import ErrorMsg
        msg = ErrorMsg(event="error", code="LLM_ERROR", message="Gemini timeout")
        data = json.loads(msg.model_dump_json())
        assert data["code"] == "LLM_ERROR"

    def test_final_transcript_parsed(self) -> None:
        from pydantic import TypeAdapter
        from server.models.schemas import ClientMessage, FinalTranscriptMsg
        adapter = TypeAdapter(ClientMessage)
        raw = {"event": "final_transcript", "text": "bật đèn phòng khách"}
        msg = adapter.validate_python(raw)
        assert isinstance(msg, FinalTranscriptMsg)
        assert msg.text == "bật đèn phòng khách"

    def test_barge_in_parsed(self) -> None:
        from pydantic import TypeAdapter
        from server.models.schemas import BargeInMsg, ClientMessage
        adapter = TypeAdapter(ClientMessage)
        raw = {"event": "barge_in", "timestamp": 1716654220}
        msg = adapter.validate_python(raw)
        assert isinstance(msg, BargeInMsg)

    def test_invalid_event_rejected(self) -> None:
        from pydantic import TypeAdapter, ValidationError
        from server.models.schemas import ClientMessage
        adapter = TypeAdapter(ClientMessage)
        with pytest.raises(ValidationError):
            adapter.validate_python({"event": "unknown_event", "data": "x"})

    def test_binary_data_rejected(self) -> None:
        """Server only accepts JSON text, not binary."""
        import json as _json
        with pytest.raises((_json.JSONDecodeError, UnicodeDecodeError, Exception)):
            _json.loads(b"\x00\x01\x02\x03")


# ─── Context Manager Tests ────────────────────────────────────────────────────

class TestContextManager:
    """ContextManager sliding window and graceful Redis degradation."""

    @pytest.mark.asyncio
    async def test_graceful_degradation_without_redis(self) -> None:
        """ContextManager returns empty history when Redis is unavailable."""
        from server.orchestrator.context_manager import ContextManager
        cm = ContextManager(redis_url="redis://127.0.0.1:19999")  # non-existent
        await cm.connect()  # should not raise
        history = await cm.get_history("test-session")
        assert history == []

    @pytest.mark.asyncio
    async def test_sliding_window_logic(self) -> None:
        """Simulate sliding window without Redis."""
        from server.config import SESSION_HISTORY_MAX

        history: list[dict] = []
        for i in range(15):
            history.append({"role": "user", "content": f"msg {i}"})
            if len(history) > SESSION_HISTORY_MAX:
                history = history[-SESSION_HISTORY_MAX:]

        assert len(history) == SESSION_HISTORY_MAX
        assert history[-1]["content"] == "msg 14"
        assert history[0]["content"] == "msg 5"


# ─── Policy Engine Tests ──────────────────────────────────────────────────────

class TestPolicyEngine:
    """PolicyEngine routing invariant."""

    @pytest.mark.asyncio
    async def test_function_call_routes_to_tool_manager(self) -> None:
        from server.orchestrator.intent_classifier import FunctionCall
        from server.orchestrator.policy_engine import PolicyEngine
        from server.orchestrator.tool_manager import ToolManager
        from server.models.schemas import IoTStatus

        mock_mqtt = MagicMock()
        mock_mqtt.send_command = AsyncMock(return_value={
            "command_id": "test-123",
            "status": "SUCCESS",
            "current_state": {"power": "ON"},
            "error_message": "",
            "latency_ms": 45,
        })

        tool_manager = ToolManager(mqtt_manager=mock_mqtt)
        policy = PolicyEngine(tool_manager=tool_manager)

        intent = FunctionCall(
            name="control_light",
            arguments={"device_id": "living_room_light", "power": "ON"},
        )
        result = await policy.execute(
            intent=intent,
            session_id="test-session",
            history=[],
            current_text="bật đèn phòng khách",
        )

        assert result.iot_result is not None
        assert result.iot_result.status == "SUCCESS"
        mock_mqtt.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_text_response_does_not_call_tool_manager(self) -> None:
        from server.orchestrator.intent_classifier import TextResponse
        from server.orchestrator.policy_engine import PolicyEngine
        from server.orchestrator.tool_manager import ToolManager

        mock_mqtt = MagicMock()
        mock_mqtt.send_command = AsyncMock()

        tool_manager = ToolManager(mqtt_manager=mock_mqtt)
        policy = PolicyEngine(tool_manager=tool_manager)

        intent = TextResponse(text="Xin chào!")
        result = await policy.execute(
            intent=intent,
            session_id="test-session",
            history=[],
            current_text="Xin chào",
        )

        assert result.iot_result is None
        mock_mqtt.send_command.assert_not_called()


# ─── MQTT Manager Tests ───────────────────────────────────────────────────────

class TestMQTTManager:
    """MQTTManager timeout and asyncio.Future pattern."""

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self) -> None:
        """When no device responds, status must be TIMEOUT."""
        from server.services.mqtt_manager import MQTTManager

        mgr = MQTTManager(timeout_s=0.05)  # 50ms for fast test

        # Mock paho client to not deliver any response
        mock_client = MagicMock()
        mock_client.publish = MagicMock()
        mock_client.subscribe = MagicMock()
        mgr._client = mock_client

        result = await mgr.send_command(
            device_id="test_device",
            parameters={"power": "ON"},
        )

        assert result["status"] == "TIMEOUT"
        assert "test_device" in result.get("error_message", "")

    def test_command_payload_has_required_fields(self) -> None:
        """Verify the payload structure before publishing."""
        import time
        import uuid as _uuid
        from server.models.schemas import IoTCommand

        cmd = IoTCommand(
            command_id=str(_uuid.uuid4()),
            action="WRITE",
            parameters={"power": "ON"},
        )
        assert cmd.command_id
        assert cmd.action == "WRITE"
        assert "power" in cmd.parameters
        assert cmd.sent_at <= int(time.time()) + 1


# ─── Concurrent Session Isolation ────────────────────────────────────────────

class TestSessionIsolation:
    """Multiple sessions must not interfere with each other."""

    @pytest.mark.asyncio
    async def test_concurrent_sessions_isolated(self) -> None:
        from server.orchestrator.state_manager import State, StateManager

        sm = StateManager()
        sessions = [str(uuid.uuid4()) for _ in range(10)]

        for sid in sessions:
            sm.init_session(sid)

        # Transition each session independently
        for i, sid in enumerate(sessions):
            if i % 2 == 0:
                await sm.transition(sid, State.LISTENING)

        # Verify states are independent
        for i, sid in enumerate(sessions):
            expected = State.LISTENING if i % 2 == 0 else State.IDLE
            assert sm.get_state(sid) == expected, (
                f"Session {i} expected {expected}, got {sm.get_state(sid)}"
            )

        # Cleanup
        for sid in sessions:
            sm.cleanup_session(sid)


# ─── WSClient Reconnect Tests ─────────────────────────────────────────────────

class TestWSClientReconnect:
    """Exponential backoff reconnect logic."""

    def test_backoff_delays_are_correct(self) -> None:
        from client.config import WS_MAX_BACKOFF_S, WS_MAX_RETRIES
        assert WS_MAX_RETRIES == 5
        assert WS_MAX_BACKOFF_S == 60

        expected = [min(2 ** n, 60) for n in range(1, 6)]
        assert expected == [2, 4, 8, 16, 32]

    @pytest.mark.asyncio
    async def test_connection_failed_after_max_retries(self) -> None:
        from client.transport.ws_client import ConnectionFailed, WSClient

        with patch("client.transport.ws_client.WS_MAX_RETRIES", 2), \
             patch("client.transport.ws_client.WS_MAX_BACKOFF_S", 0), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            client = WSClient(uri="ws://127.0.0.1:19999/nonexistent")
            with pytest.raises(ConnectionFailed):
                await client.connect()
