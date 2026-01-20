"""
Memory Tool for storing user-specific information.

This tool allows the LLM to save memories about the user for future conversations.
The memories are passed in via override_kwargs which contains the current list of
memories that exist for the user.
"""

from typing import Any
from typing import cast

from pydantic import BaseModel
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.llm.interfaces import LLM
from onyx.secondary_llm_flows.memory_update import process_memory_update
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.interface import Tool
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import ToolResponse
from onyx.utils.logger import setup_logger


logger = setup_logger()


MEMORY_FIELD = "memory"


class MemoryToolOverrideKwargs(BaseModel):
    # Not including the Team Information or User Preferences because these are less likely to contribute to building the memory
    # Things like the user's name is important because the LLM may create a memory like "Dave prefers light mode." instead of
    # User prefers light mode.
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
        # TODO
        pass

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: MemoryToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        memory = cast(str, llm_kwargs[MEMORY_FIELD])

        existing_memories = override_kwargs.existing_memories
        chat_history = override_kwargs.chat_history

        # Determine if this should be an add or update operation
        memory_text, index_to_replace = process_memory_update(
            new_memory=memory,
            existing_memories=existing_memories,
            chat_history=chat_history,
            llm=self.llm,
            user_name=override_kwargs.user_name,
            user_email=override_kwargs.user_email,
            user_role=override_kwargs.user_role,
        )

        # TODO: the data should be return and processed outside of the tool
        # Persisted to the db for future conversations
        # The actual persistence of the memory will be handled by the caller
        # This tool just returns the memory to be saved
        logger.info(f"New memory to be added: {memory_text}")

        return ToolResponse(
            rich_response=memory_text,
            llm_facing_response=f"New memory added: {memory_text}",
        )
