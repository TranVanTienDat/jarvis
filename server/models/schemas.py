"""
Pydantic schemas for all WebSocket messages and MQTT payloads.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class SessionState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


# ─── Client → Server Messages ─────────────────────────────────────────────────

class PartialTranscriptMsg(BaseModel):
    event: Literal["partial_transcript"]
    token: str


class FinalTranscriptMsg(BaseModel):
    event: Literal["final_transcript"]
    text: str


class BargeInMsg(BaseModel):
    event: Literal["barge_in"]
    timestamp: int = Field(default_factory=lambda: int(time.time()))


class STTErrorMsg(BaseModel):
    event: Literal["stt_error"]
    message: str


ClientMessage = Annotated[
    Union[PartialTranscriptMsg, FinalTranscriptMsg, BargeInMsg, STTErrorMsg],
    Field(discriminator="event"),
]


# ─── Server → Client Messages ─────────────────────────────────────────────────

class AudioChunkMsg(BaseModel):
    event: Literal["audio_chunk"]
    data: str        # base64-encoded PCM bytes
    seq: int         # sequence number for ordering


class ClearBufferMsg(BaseModel):
    event: Literal["clear_buffer"]


class SessionInitMsg(BaseModel):
    event: Literal["session_init"]
    session_id: str


class StateChangeMsg(BaseModel):
    event: Literal["state_change"]
    state: SessionState


class ErrorMsg(BaseModel):
    event: Literal["error"]
    code: str
    message: str


ServerMessage = Annotated[
    Union[AudioChunkMsg, ClearBufferMsg, SessionInitMsg, StateChangeMsg, ErrorMsg],
    Field(discriminator="event"),
]


# ─── MQTT Payloads ────────────────────────────────────────────────────────────

class IoTCommand(BaseModel):
    command_id: str
    action: Literal["WRITE", "READ"]
    parameters: dict
    sent_at: int = Field(default_factory=lambda: int(time.time()))


class IoTStatus(BaseModel):
    command_id: str
    status: Literal["SUCCESS", "FAILURE", "TIMEOUT"]
    current_state: dict = Field(default_factory=dict)
    error_message: str = ""
    latency_ms: int = 0


# ─── Internal Models ──────────────────────────────────────────────────────────

class ConversationMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class PolicyResult(BaseModel):
    iot_result: Optional[IoTStatus] = None
    llm_context: list[ConversationMessage] = Field(default_factory=list)
