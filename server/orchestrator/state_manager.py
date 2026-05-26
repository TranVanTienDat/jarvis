"""
State machine manager for WebSocket sessions.
Enforces valid state transitions and logs all changes.
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Dict

logger = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"


# Valid transitions: from_state → set of allowed to_states
VALID_TRANSITIONS: Dict[State, set] = {
    State.IDLE:       {State.LISTENING, State.ERROR},
    State.LISTENING:  {State.PROCESSING, State.IDLE, State.ERROR},
    State.PROCESSING: {State.SPEAKING, State.IDLE, State.ERROR},
    State.SPEAKING:   {State.LISTENING, State.IDLE, State.ERROR},
    State.ERROR:      {State.IDLE},
}


class StateManager:
    """Per-session state machine.

    Thread-safe via per-session asyncio.Lock.
    """

    def __init__(self) -> None:
        self._states: Dict[str, State] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_session(self, session_id: str) -> None:
        """Register a new session with initial state IDLE."""
        self._states[session_id] = State.IDLE
        self._locks[session_id] = asyncio.Lock()
        logger.info("[%s] Session initialised → IDLE", session_id)

    async def transition(self, session_id: str, new_state: State) -> bool:
        """Attempt to transition session to new_state.

        Returns True on success, False if the transition is invalid.
        Invalid transitions are logged as WARNING and leave state unchanged.
        """
        if session_id not in self._states:
            self.init_session(session_id)

        async with self._locks[session_id]:
            current = self._states[session_id]

            if new_state not in VALID_TRANSITIONS.get(current, set()):
                logger.warning(
                    "[%s] Invalid transition %s → %s (rejected).",
                    session_id,
                    current.value,
                    new_state.value,
                )
                return False

            self._states[session_id] = new_state
            logger.info(
                "[%s] State transition: %s → %s",
                session_id,
                current.value,
                new_state.value,
            )
            return True

    def get_state(self, session_id: str) -> State:
        """Return the current state for a session (default IDLE)."""
        return self._states.get(session_id, State.IDLE)

    def cleanup_session(self, session_id: str) -> None:
        """Remove all state data for a closed session."""
        self._states.pop(session_id, None)
        self._locks.pop(session_id, None)
        logger.info("[%s] Session cleaned up.", session_id)
