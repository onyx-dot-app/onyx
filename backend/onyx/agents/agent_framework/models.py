from typing import Any
from typing import Literal
from typing import TypeAlias

from pydantic import BaseModel

from onyx.llm.model_response import ModelResponseStream


class ToolCallStreamItem(BaseModel):
    call_id: str | None = None

    id: str | None = None

    name: str | None = None

    arguments: str | None = None

    type: Literal["function_call"] = "function_call"

    index: int | None = None


class ToolCallOutputStreamItem(BaseModel):
    call_id: str | None = None

    output: Any

    type: Literal["function_call_output"] = "function_call_output"


RunItemStreamEventDetails: TypeAlias = ToolCallStreamItem | ToolCallOutputStreamItem


class RunItemStreamEvent(BaseModel):
    type: Literal[
        "message_start",
        "message_done",
        "reasoning_start",
        "reasoning_done",
        "tool_call",
        "tool_call_output",
    ]
    details: RunItemStreamEventDetails | None = None


StreamEvent: TypeAlias = ModelResponseStream | RunItemStreamEvent
