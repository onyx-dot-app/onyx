"""Persisted tool descriptor for the native memory capability.

The registry identity stays stable so saved memory events can still be replayed.
The chat agent replaces this descriptor with Pydantic AI's Memory capability.
"""

from typing import Any

from pydantic import BaseModel

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.interface import Tool
from onyx.tools.models import ToolResponse


class MemoryTool(Tool[BaseModel]):
    NAME = "add_memory"
    DISPLAY_NAME = "Memory"
    DESCRIPTION = "Save memories about the user for future conversations."

    def __init__(self, tool_id: int, emitter: Emitter) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    def tool_definition(self) -> dict[str, Any]:
        raise RuntimeError(
            "Memory schemas are provided by the native Memory capability"
        )

    def emit_start(self, placement: Placement) -> None:
        del placement

    def run(
        self, placement: Placement, override_kwargs: BaseModel, **llm_kwargs: Any
    ) -> ToolResponse:
        del placement, override_kwargs, llm_kwargs
        raise RuntimeError("Memory runs through the native Memory capability")
