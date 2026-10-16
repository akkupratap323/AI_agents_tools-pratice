"""
tools/_base.py - what every tool module provides.

Each tool file exposes one SPEC = ToolSpec(...) that holds BOTH halves of the
tool side by side:
    the contract the model sees  (name, description, properties, required)
    the code that runs           (handler)

Keeping them in one object, in one file, is the structural fix for
schema/handler drift (the "schema says start, handler says start_date" bug).
The registry in tools/__init__.py additionally verifies, at import time, that
the handler's signature matches the schema exactly.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str          # what / when / returns / limits / errors
    properties: dict          # JSON Schema properties: names == handler params
    required: list            # params without defaults in the handler
    handler: Callable

    def to_chat_completions(self):
        """Wire format for OpenAI-compatible Chat Completions (DeepSeek)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": list(self.required),
                    "additionalProperties": False,   # unknown keys are not allowed
                },
            },
        }
