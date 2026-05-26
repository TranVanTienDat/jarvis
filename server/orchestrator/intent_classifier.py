"""
Intent classifier using Gemini Function Calling.
Classifies user text as either an IoT control command (FunctionCall)
or a general conversation response (TextResponse).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from server.config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)


# ─── Result types ─────────────────────────────────────────────────────────────

@dataclass
class FunctionCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class TextResponse:
    text: str


# ─── IoT function schemas for Gemini ──────────────────────────────────────────

IOT_FUNCTION_SCHEMAS = [
    {
        "name": "control_light",
        "description": "Bat/tat hoac dieu chinh do sang va mau sac den trong nha.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "ID thiet bi den"},
                "power": {"type": "string", "enum": ["ON", "OFF"]},
                "brightness": {"type": "integer", "description": "Do sang 0-100"},
                "color_temp": {"type": "integer", "description": "Nhiet do mau Kelvin"},
            },
            "required": ["device_id", "power"],
        },
    },
    {
        "name": "control_ac",
        "description": "Bat/tat hoac dieu chinh nhiet do dieu hoa.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "power": {"type": "string", "enum": ["ON", "OFF"]},
                "temperature": {"type": "integer", "description": "Nhiet do 16-30C"},
                "mode": {"type": "string", "enum": ["COOL", "HEAT", "FAN", "AUTO"]},
            },
            "required": ["device_id", "power"],
        },
    },
    {
        "name": "control_lock",
        "description": "Khoa hoac mo khoa cua thong minh.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
                "action": {"type": "string", "enum": ["LOCK", "UNLOCK"]},
            },
            "required": ["device_id", "action"],
        },
    },
    {
        "name": "query_device_status",
        "description": "Truy van trang thai hien tai cua mot thiet bi IoT.",
        "parameters": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string"},
            },
            "required": ["device_id"],
        },
    },
]


# ─── Classifier ───────────────────────────────────────────────────────────────

class IntentClassifier:
    """Classifies user intent using Gemini Function Calling (google-genai SDK)."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=GEMINI_API_KEY)

    async def classify(
        self,
        text: str,
        history: list[dict],
    ) -> FunctionCall | TextResponse:
        """Classify the user's intent.

        Returns FunctionCall if an IoT action was detected, TextResponse otherwise.
        """
        contents = self._build_contents(history, text)

        try:
            tools = [types.Tool(function_declarations=IOT_FUNCTION_SCHEMAS)]
            response = await self._client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=tools,
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(mode="AUTO")
                    ),
                ),
            )

            # Check for function call in response parts
            for part in response.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call and part.function_call.name:
                    fc = part.function_call
                    args = dict(fc.args) if fc.args else {}
                    logger.info("Intent: FunctionCall(%s, %s)", fc.name, args)
                    return FunctionCall(name=fc.name, arguments=args)

            text_out = response.text or ""
            logger.info("Intent: TextResponse (len=%d)", len(text_out))
            return TextResponse(text=text_out)

        except Exception as exc:
            logger.error("IntentClassifier error: %s", exc)
            return TextResponse(text="")

    @staticmethod
    def _build_contents(history: list[dict], current_text: str) -> list[dict]:
        """Convert history + current text into Gemini contents format."""
        contents = []
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
        contents.append({"role": "user", "parts": [{"text": current_text}]})
        return contents
