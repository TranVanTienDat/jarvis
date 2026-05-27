"""
Prompt definitions for all LLM providers.

Modules:
    system  — system-level prompts (default smart-home assistant, etc.)
"""
from server.prompts.system import DEFAULT_SYSTEM_PROMPT

__all__ = ["DEFAULT_SYSTEM_PROMPT"]
