"""
Tool manager — executes external tools (IoT MQTT, weather API).
Called by PolicyEngine when IntentClassifier returns a FunctionCall.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from server.models.schemas import IoTStatus
from server.services.mqtt_manager import MQTTManager

logger = logging.getLogger(__name__)

# Map Gemini function names → device_id prefix conventions
_FUNCTION_DEVICE_MAP: dict[str, str] = {
    "control_light": "light",
    "control_ac": "ac",
    "control_lock": "lock",
    "query_device_status": "device",
}


@dataclass
class WeatherResult:
    location: str
    description: str
    temperature_c: float


class ToolManager:
    """Executes tool calls dispatched by PolicyEngine.

    Currently supports:
      - IoT device control via MQTTManager
      - Weather query (stub — replace with real API)
    """

    def __init__(self, mqtt_manager: MQTTManager) -> None:
        self._mqtt = mqtt_manager

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def trigger_iot_action(
        self,
        function_name: str,
        arguments: dict[str, Any],
    ) -> IoTStatus:
        """Execute an IoT control command via MQTT.

        Args:
            function_name: Gemini function name (e.g. "control_light").
            arguments:     Function arguments from Gemini FunctionCall.

        Returns:
            IoTStatus with SUCCESS or TIMEOUT/FAILURE.
        """
        device_id = arguments.get("device_id", "unknown_device")

        # Build parameters dict (everything except device_id)
        parameters = {k: v for k, v in arguments.items() if k != "device_id"}

        logger.info(
            "ToolManager: trigger_iot_action(%s) → device=%s params=%s",
            function_name,
            device_id,
            parameters,
        )

        raw = await self._mqtt.send_command(
            device_id=device_id,
            parameters=parameters,
        )

        return IoTStatus(
            command_id=raw.get("command_id", ""),
            status=raw.get("status", "FAILURE"),
            current_state=raw.get("current_state", {}),
            error_message=raw.get("error_message", ""),
            latency_ms=raw.get("latency_ms", 0),
        )

    async def query_weather(self, location: str) -> WeatherResult:
        """Query current weather for a location.

        Stub implementation — replace with a real weather API call.
        """
        logger.info("ToolManager: query_weather(%s)", location)
        # TODO: integrate with OpenWeatherMap or similar
        return WeatherResult(
            location=location,
            description="Trời nắng, ít mây",
            temperature_c=28.0,
        )
