from typing import TypedDict

from onyx.tools.message import ToolCallSummary
from onyx.tools.models import ToolCallFinalResult
from onyx.tools.models import ToolCallKickoff
from onyx.tools.models import ToolResponse
from onyx.tools.tool import Tool

# States contain values that change over the course of graph execution,
# Config is for values that are set at the start and never change.
# If you are using a value from the config and realize it needs to change,
# you should add it to the state and use/update the version in the state.

## Graph Input State


class BasicInput(TypedDict):
    should_stream_answer: bool


## Graph Output State


class BasicOutput(TypedDict):
    pass


## Update States
class ToolCallUpdate(TypedDict):
    tool_call_summary: ToolCallSummary
    tool_call_kickoff: ToolCallKickoff
    tool_call_responses: list[ToolResponse]
    tool_call_final_result: ToolCallFinalResult


class ToolChoice(TypedDict):
    tool: Tool
    tool_args: dict
    id: str | None


class ToolChoiceUpdate(TypedDict):
    tool_choice: ToolChoice | None


## Graph State


class BasicState(
    BasicInput,
    ToolCallUpdate,
    ToolChoiceUpdate,
    BasicOutput,
):
    pass
