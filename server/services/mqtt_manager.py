"""
Async MQTT manager — wraps paho-mqtt with asyncio.Future for awaitable commands.
Publishes IoT control commands and waits for device acknowledgement.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Optional

import paho.mqtt.client as mqtt

from server.config import MQTT_BROKER_HOST, MQTT_BROKER_PORT, MQTT_COMMAND_TIMEOUT_S

logger = logging.getLogger(__name__)

_CONTROL_TOPIC = "iot/control/{device_id}"
_STATUS_TOPIC = "iot/status/{device_id}"


class MQTTManager:
    """Async MQTT client using asyncio.Future for request/response pattern.

    Property 15 — every published command contains: command_id, action,
    parameters, sent_at.

    Property 16 — response arriving within MQTT_COMMAND_TIMEOUT_S → SUCCESS;
    no response within timeout → TIMEOUT; late responses are ignored.
    """

    def __init__(
        self,
        broker_host: str = MQTT_BROKER_HOST,
        broker_port: int = MQTT_BROKER_PORT,
        timeout_s: float = MQTT_COMMAND_TIMEOUT_S,
    ) -> None:
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._timeout_s = timeout_s
        self._pending: Dict[str, Dict] = {}  # command_id → {future, loop}
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_message = self._on_message
        self._client.on_connect = self._on_connect

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the MQTT broker and start the network loop."""
        self._client.connect(self._broker_host, self._broker_port)
        self._client.loop_start()
        logger.info("MQTTManager connected to %s:%d", self._broker_host, self._broker_port)

    def disconnect(self) -> None:
        """Stop the network loop and disconnect."""
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("MQTTManager disconnected.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_command(
        self,
        device_id: str,
        parameters: dict,
        action: str = "WRITE",
    ) -> dict:
        """Publish a control command and await the device acknowledgement.

        Returns:
            dict with "status": "SUCCESS" | "TIMEOUT" and optional fields.
        """
        command_id = str(uuid.uuid4())
        payload = {
            "command_id": command_id,
            "action": action,
            "parameters": parameters,
            "sent_at": int(time.time()),
        }

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[command_id] = {"future": future, "loop": loop}

        # Subscribe to status topic before publishing
        status_topic = _STATUS_TOPIC.format(device_id=device_id)
        self._client.subscribe(status_topic)

        # Publish command
        control_topic = _CONTROL_TOPIC.format(device_id=device_id)
        self._client.publish(control_topic, json.dumps(payload))
        logger.debug("MQTT publish → %s: %s", control_topic, payload)

        try:
            result = await asyncio.wait_for(future, timeout=self._timeout_s)
            logger.info("IoT command %s → SUCCESS (latency: %dms)", command_id, result.get("latency_ms", 0))
            return result
        except asyncio.TimeoutError:
            logger.warning("IoT command %s → TIMEOUT after %.0fms", command_id, self._timeout_s * 1000)
            return {
                "command_id": command_id,
                "status": "TIMEOUT",
                "current_state": {},
                "error_message": f"Device {device_id} did not respond within {int(self._timeout_s * 1000)}ms.",
                "latency_ms": int(self._timeout_s * 1000),
            }
        finally:
            self._pending.pop(command_id, None)

    # ------------------------------------------------------------------
    # paho-mqtt callbacks (called from MQTT network thread)
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code == 0 or str(reason_code) == "Success":
            logger.debug("MQTT broker connection established.")
        else:
            logger.error("MQTT connection failed with code %s", reason_code)

    def _on_message(self, client, userdata, message) -> None:
        """Handle incoming status messages from IoT devices."""
        try:
            payload = json.loads(message.payload.decode())
            command_id = payload.get("command_id")

            if command_id and command_id in self._pending:
                entry = self._pending[command_id]
                loop: asyncio.AbstractEventLoop = entry["loop"]
                future: asyncio.Future = entry["future"]

                if not future.done():
                    loop.call_soon_threadsafe(future.set_result, payload)
        except Exception as exc:
            logger.warning("MQTTManager._on_message error: %s", exc)
