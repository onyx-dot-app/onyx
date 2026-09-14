"""
Memory Tool for storing user-specific information.

This tool allows the LLM to save memories about the user for future conversations.
The memories are passed in via override_kwargs which contains the current list of
memories that exist for the user.
"""

from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.db.memory import add_memory, update_memory_at_index
from onyx.llm.cancellation import check_cancelled
from onyx.llm.interfaces import LLM
from onyx.llm.models import ToolResult
from onyx.secondary_llm_flows.memory_update import process_memory_update
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    MemoryToolDelta,
    MemoryToolStart,
    Packet,
)
from onyx.tools.interface import Tool
from onyx.tools.models import (
    ChatMinimalTextMessage,
    MemoryToolResponseSnapshot,
    ToolCallException,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_incognito_record_mode

logger = setup_logger()


MEMORY_FIELD = "memory"


class MemoryToolOverrideKwargs(BaseModel):
    # User identity helps write standalone memories.
    user_id: UUID | None
    user_name: str | None
    user_email: str | None
    user_role: str | None
    existing_memories: list[str]
    chat_history: list[ChatMinimalTextMessage]


class MemoryTool(Tool[MemoryToolOverrideKwargs]):
    NAME = "add_memory"
    DISPLAY_NAME = "Add Memory"
    DESCRIPTION = "Save memories about the user for future conversations."

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        llm: LLM,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self.llm = llm

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

    @override
    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        MEMORY_FIELD: {
                            "type": "string",
                            "description": (
                                "The text of the memory to add or update. "
                                "Should be a concise, standalone statement that "
                                "captures the key information. For example: "
                                "'User prefers dark mode' or 'User's favorite frontend framework is React'."
                            ),
                        },
                    },
                    "required": [MEMORY_FIELD],
                },
            },
        }

    @override
    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(Packet(placement=placement, obj=MemoryToolStart()))

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: MemoryToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResult:
        if MEMORY_FIELD not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing required '{MEMORY_FIELD}' parameter in add_memory tool call",
                llm_facing_message=(
                    f"The add_memory tool requires a '{MEMORY_FIELD}' parameter containing "
                    f"the memory text to save. Please provide like: "
                    f'{{"memory": "User prefers dark mode"}}'
                ),
            )
        memory = cast(str, llm_kwargs[MEMORY_FIELD])

        user_id = override_kwargs.user_id
        if get_current_incognito_record_mode() is not None:
            return ToolResult(
                content="Error: memories cannot be saved from an incognito chat. Tell the user their request was not saved.",
                is_error=True,
            )
        if user_id is None:
            return ToolResult(
                content="Error: memory could not be saved without an authenticated user.",
                is_error=True,
            )

        existing_memories = override_kwargs.existing_memories
        chat_history = override_kwargs.chat_history

        memory_text, index_to_replace = process_memory_update(
            new_memory=memory,
            existing_memories=existing_memories,
            chat_history=chat_history,
            llm=self.llm,
            user_name=override_kwargs.user_name,
            user_email=override_kwargs.user_email,
            user_role=override_kwargs.user_role,
        )

        check_cancelled()
        try:
            memory_id = (
                update_memory_at_index(
                    user_id=user_id,
                    index=index_to_replace,
                    new_text=memory_text,
                )
                if index_to_replace is not None
                else add_memory(user_id=user_id, memory_text=memory_text)
            )
            if memory_id is None:
                logger.warning("Memory update target was not found")
                return ToolResult(
                    content="Error: memory could not be saved.", is_error=True
                )
        except Exception:
            logger.exception("Memory write failed")
            return ToolResult(
                content="Error: memory could not be saved. Tell the user their request was not saved.",
                is_error=True,
            )
        snapshot = MemoryToolResponseSnapshot(
            memory_text=memory_text,
            operation="update" if index_to_replace is not None else "add",
            memory_id=memory_id,
            index=index_to_replace,
        )
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=MemoryToolDelta(
                    memory_text=snapshot.memory_text,
                    operation=snapshot.operation,
                    memory_id=snapshot.memory_id,
                    index=snapshot.index,
                ),
            )
        )
        return ToolResult(content=snapshot.model_dump_json(), details=snapshot)
