import json
from typing import Literal

from onyx.db.memory import UserMemoryContext, add_memory, update_memory_at_index
from onyx.tools.models import (
    CustomToolCallSummary,
    MemoryToolResponseSnapshot,
    ToolResponse,
)
from onyx.tools.tool_implementations.memory.models import MemoryToolResponse
from shared_configs.contextvars import get_current_incognito_record_mode


def persist_tool_result(
    tool_response: ToolResponse, user_memory_context: UserMemoryContext | None
) -> str:
    """Persist memory effects and return the UI snapshot for any tool result."""
    memory_snapshot: MemoryToolResponseSnapshot | None = None
    incognito_memory_refusal: str | None = None
    if isinstance(tool_response.rich_response, MemoryToolResponse):
        if get_current_incognito_record_mode() is not None:
            incognito_memory_refusal = "Error: memories cannot be saved from an incognito chat. Tell the user their request was not saved."
        else:
            persisted_memory_id: int | None = None
            if user_memory_context and user_memory_context.user_id:
                if tool_response.rich_response.index_to_replace is not None:
                    persisted_memory_id = update_memory_at_index(
                        user_id=user_memory_context.user_id,
                        index=tool_response.rich_response.index_to_replace,
                        new_text=tool_response.rich_response.memory_text,
                    )
                else:
                    persisted_memory_id = add_memory(
                        user_id=user_memory_context.user_id,
                        memory_text=tool_response.rich_response.memory_text,
                    )
            operation: Literal["add", "update"] = (
                "update"
                if tool_response.rich_response.index_to_replace is not None
                else "add"
            )
            memory_snapshot = MemoryToolResponseSnapshot(
                memory_text=tool_response.rich_response.memory_text,
                operation=operation,
                memory_id=persisted_memory_id,
                index=tool_response.rich_response.index_to_replace,
            )
    if incognito_memory_refusal:
        saved_response = incognito_memory_refusal
        tool_response.llm_facing_response = incognito_memory_refusal
    elif memory_snapshot:
        saved_response = json.dumps(memory_snapshot.model_dump())
    elif isinstance(tool_response.rich_response, CustomToolCallSummary):
        saved_response = json.dumps(tool_response.rich_response.model_dump())
    elif isinstance(tool_response.rich_response, str):
        saved_response = tool_response.rich_response
    else:
        saved_response = tool_response.llm_facing_response
    return saved_response
