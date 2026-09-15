from pydantic import BaseModel
from typing_extensions import override

from onyx.agents.tools import ToolExecutionMode, ToolInvocation, ToolProgress
from onyx.db.memory import add_memory, update_memory_at_index
from onyx.llm.cancellation import check_cancelled
from onyx.llm.interfaces import LLM
from onyx.llm.models import ToolResult
from onyx.secondary_llm_flows.memory_update import process_memory_update
from onyx.tools.interface import (
    FunctionToolDefinition,
    Tool,
    ToolContext,
    parse_tool_arguments,
    tool_message_history,
)
from onyx.tools.models import ToolCallException
from onyx.tools.progress import MemoryOperation, MemoryStarted, MemoryUpdated
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_incognito_record_mode

logger = setup_logger()


MEMORY_FIELD = "memory"


class MemoryArguments(BaseModel):
    memory: str


class MemoryTool(Tool):
    NAME = "add_memory"
    DISPLAY_NAME = "Add Memory"
    DESCRIPTION = "Save memories about the user for future conversations."

    def __init__(
        self,
        tool_id: int,
        llm: LLM,
    ) -> None:
        self._id = tool_id
        self.llm = llm

    @property
    @override
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.SEQUENTIAL

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
    def tool_definition(self) -> FunctionToolDefinition:
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
    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:
        invocation.update(ToolProgress(details=MemoryStarted()))
        if MEMORY_FIELD not in invocation.arguments:
            raise ToolCallException(
                message=f"Missing required '{MEMORY_FIELD}' parameter in add_memory tool call",
                llm_facing_message=(
                    f"The add_memory tool requires a '{MEMORY_FIELD}' parameter containing "
                    f"the memory text to save. Please provide like: "
                    f'{{"memory": "User prefers dark mode"}}'
                ),
            )
        memory = parse_tool_arguments(MemoryArguments, invocation.arguments).memory

        user_memory = context.user_memory_context
        user_id = user_memory.user_id if user_memory else None
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

        existing_memories = list(user_memory.memories) if user_memory else []
        chat_history = tool_message_history(list(invocation.messages))

        memory_text, index_to_replace = process_memory_update(
            new_memory=memory,
            existing_memories=existing_memories,
            chat_history=chat_history,
            llm=self.llm,
            user_name=user_memory.user_info.name if user_memory else None,
            user_email=user_memory.user_info.email if user_memory else None,
            user_role=user_memory.user_info.role if user_memory else None,
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
        snapshot = MemoryUpdated(
            memory_text=memory_text,
            operation=MemoryOperation.UPDATE
            if index_to_replace is not None
            else MemoryOperation.ADD,
            memory_id=memory_id,
            index=index_to_replace,
        )
        invocation.update(ToolProgress(details=snapshot))
        return ToolResult(content=snapshot.model_dump_json(), details=snapshot)
