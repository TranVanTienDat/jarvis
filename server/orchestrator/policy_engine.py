"""
Policy engine — routes intents to the correct action handler.

Rules:
  FunctionCall  → ToolManager (IoT control), then LLM with result context
  TextResponse  → LLM directly (no tool invocation)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from server.models.schemas import ConversationMessage, IoTStatus, PolicyResult
from server.orchestrator.intent_classifier import FunctionCall, TextResponse

if TYPE_CHECKING:
    from server.orchestrator.tool_manager import ToolManager

logger = logging.getLogger(__name__)


class PolicyEngine:
    """Executes business rules based on classified intent.

    Invariant (Property 8):
      - FunctionCall  → ToolManager is called; LLM is NOT called directly here.
      - TextResponse  → ToolManager is NOT called; result carries empty iot_result.
    """

    def __init__(self, tool_manager: "ToolManager") -> None:
        self._tool_manager = tool_manager

    async def execute(
        self,
        intent: FunctionCall | TextResponse,
        session_id: str,
        history: list[dict],
        current_text: str,
    ) -> PolicyResult:
        """Execute the policy for the given intent.

        Returns a PolicyResult containing:
          - iot_result: IoTStatus if a tool was invoked, else None
          - llm_context: conversation messages to pass to the LLM
        """
        if isinstance(intent, FunctionCall):
            return await self._handle_function_call(intent, session_id, history, current_text)
        else:
            return self._handle_text_response(intent, history, current_text)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_function_call(
        self,
        intent: FunctionCall,
        session_id: str,
        history: list[dict],
        current_text: str,
    ) -> PolicyResult:
        """Route IoT function call to ToolManager and build LLM context."""
        logger.info("[%s] PolicyEngine: routing FunctionCall(%s) to ToolManager", session_id, intent.name)

        iot_result: IoTStatus = await self._tool_manager.trigger_iot_action(
            function_name=intent.name,
            arguments=intent.arguments,
        )

        # Build context for LLM including IoT result
        llm_context = self._build_context(history, current_text)
        if iot_result.status == "SUCCESS":
            llm_context.append(
                ConversationMessage(
                    role="system",
                    content=(
                        f"[Kết quả điều khiển thiết bị] Lệnh '{intent.name}' "
                        f"thực thi thành công. Trạng thái hiện tại: {iot_result.current_state}. "
                        f"Độ trễ: {iot_result.latency_ms}ms."
                    ),
                )
            )
        else:
            llm_context.append(
                ConversationMessage(
                    role="system",
                    content=(
                        f"[Lỗi điều khiển thiết bị] Lệnh '{intent.name}' thất bại. "
                        f"Lý do: {iot_result.error_message or iot_result.status}. "
                        "Hãy thông báo lỗi cho người dùng một cách thân thiện."
                    ),
                )
            )

        return PolicyResult(iot_result=iot_result, llm_context=llm_context)

    def _handle_text_response(
        self,
        intent: TextResponse,
        history: list[dict],
        current_text: str,
    ) -> PolicyResult:
        """Route general conversation directly to LLM (no tool call)."""
        logger.info("PolicyEngine: routing TextResponse to LLM directly.")
        llm_context = self._build_context(history, current_text)
        return PolicyResult(iot_result=None, llm_context=llm_context)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(history: list[dict], current_text: str) -> list[ConversationMessage]:
        """Convert history + current user text into ConversationMessage list."""
        messages: list[ConversationMessage] = []
        for msg in history:
            role = msg.get("role", "user")
            if role in ("user", "assistant", "system"):
                messages.append(ConversationMessage(role=role, content=msg.get("content", "")))
        messages.append(ConversationMessage(role="user", content=current_text))
        return messages
