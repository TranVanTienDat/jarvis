"""
FastAPI application entry point.
Wires up all services and starts the Uvicorn server.
"""
from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.ws_handler import make_router
from server.config import HOST, LOG_LEVEL, PORT
from server.orchestrator.context_manager import ContextManager
from server.orchestrator.core import Orchestrator
from server.orchestrator.intent_classifier import IntentClassifier
from server.orchestrator.policy_engine import PolicyEngine
from server.orchestrator.state_manager import StateManager
from server.orchestrator.tool_manager import ToolManager
from server.llms.factory import create_llm_service
from server.services.mqtt_manager import MQTTManager
from server.services.tts import TTSService

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Build application ────────────────────────────────────────────────────────

app = FastAPI(
    title="Voice Chatbot IoT Server",
    description="Real-time voice chatbot with IoT control via MQTT",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Dependency wiring ────────────────────────────────────────────────────────

# Services
_mqtt_manager = MQTTManager()
_llm_service = create_llm_service()
_tts_service = TTSService()

# Orchestrator sub-modules
_context_manager = ContextManager()
_state_manager = StateManager()
_intent_classifier = IntentClassifier()
_tool_manager = ToolManager(mqtt_manager=_mqtt_manager)
_policy_engine = PolicyEngine(tool_manager=_tool_manager)

# Central orchestrator
_orchestrator = Orchestrator(
    context_manager=_context_manager,
    intent_classifier=_intent_classifier,
    policy_engine=_policy_engine,
    state_manager=_state_manager,
    tool_manager=_tool_manager,
    llm_service=_llm_service,
    tts_service=_tts_service,
)

# Register WebSocket router
app.include_router(
    make_router(orchestrator=_orchestrator, state_manager=_state_manager)
)


# ─── Startup / shutdown events ────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup() -> None:
    logger.info("Server starting up…")
    _mqtt_manager.connect()
    await _context_manager.connect()
    logger.info("Server ready. Listening on ws://%s:%d/ws/chat", HOST, PORT)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("Server shutting down…")
    _mqtt_manager.disconnect()
    await _llm_service.close()
    await _context_manager.close()


# ─── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        reload=False,
    )
