from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, JsonValue

from onyx.deep_research.models import SpecialToolCalls
from onyx.deep_research.tool_definitions import (
    GENERATE_REPORT_TOOL_NAME,
    THINK_TOOL_NAME,
)
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    Delta,
    ResponseFunctionCall,
)
from onyx.tools.models import ToolCallKickoff
from onyx.utils.streaming_json import appended_text, parse_partial_object

# think_tool arguments are {"reasoning": "..."}
THINK_TOOL_REASONING_KEY = "reasoning"


class ThinkToolProcessorState(BaseModel):
    """State for tracking think tool processing across streaming deltas."""

    think_tool_found: bool = False
    think_tool_index: int | None = None
    think_tool_id: str | None = None
    full_arguments: str = ""  # Full accumulated arguments for final tool call
    # Partial parse of full_arguments as of the previous delta
    parsed_arguments: dict[str, JsonValue] = {}


def _extract_reasoning_chunk(state: ThinkToolProcessorState) -> str | None:
    """Return the reasoning text added since the previous delta, if any."""
    try:
        current = parse_partial_object(state.full_arguments)
    except ValueError:
        return None
    added = appended_text(state.parsed_arguments, current).get(THINK_TOOL_REASONING_KEY)
    state.parsed_arguments = current
    return added


def create_think_tool_token_processor() -> Callable[
    [Delta | None, Any], tuple[Delta | None, Any]
]:
    """
    Create a custom token processor that converts think_tool calls to reasoning content.

    When the think_tool is detected:
    - Tool call arguments are converted to reasoning_content (JSON wrapper stripped)
    - All other deltas (content, other tool calls) are dropped

    This allows non-reasoning models to emit chain-of-thought via the think_tool,
    which gets displayed as reasoning tokens in the UI.

    Returns:
        A function compatible with run_llm_step_pkt_generator's custom_token_processor parameter.
        The function takes (Delta, state) and returns (modified Delta | None, new state).
    """

    def process_token(delta: Delta | None, state: Any) -> tuple[Delta | None, Any]:
        if state is None:
            state = ThinkToolProcessorState()

        # Handle flush signal (delta=None) - emit the complete tool call
        if delta is None:
            if state.think_tool_found and state.think_tool_id:
                # Return the complete think tool call
                complete_tool_call = ChatCompletionDeltaToolCall(
                    id=state.think_tool_id,
                    index=state.think_tool_index or 0,
                    type="function",
                    function=ResponseFunctionCall(
                        name=THINK_TOOL_NAME,
                        arguments=state.full_arguments,
                    ),
                )
                return Delta(tool_calls=[complete_tool_call]), state
            return None, state

        # Check for think tool in tool_calls
        if delta.tool_calls:
            for tool_call in delta.tool_calls:
                # Detect think tool by name
                if tool_call.function and tool_call.function.name == THINK_TOOL_NAME:
                    state.think_tool_found = True
                    state.think_tool_index = tool_call.index

                # Capture tool call id when available
                if (
                    state.think_tool_found
                    and tool_call.index == state.think_tool_index
                    and tool_call.id
                ):
                    state.think_tool_id = tool_call.id

                # Accumulate arguments for the think tool
                if (
                    state.think_tool_found
                    and tool_call.index == state.think_tool_index
                    and tool_call.function
                    and tool_call.function.arguments
                ):
                    state.full_arguments += tool_call.function.arguments

                    # Try to extract reasoning content
                    reasoning_chunk = _extract_reasoning_chunk(state)
                    if reasoning_chunk:
                        # Return delta with reasoning_content to trigger reasoning streaming
                        return Delta(reasoning_content=reasoning_chunk), state

        # If think tool found, drop all other content
        if state.think_tool_found:
            return None, state

        # No think tool detected, pass through original delta
        return delta, state

    return process_token


def check_special_tool_calls(tool_calls: list[ToolCallKickoff]) -> SpecialToolCalls:
    think_tool_call: ToolCallKickoff | None = None
    generate_report_tool_call: ToolCallKickoff | None = None

    for tool_call in tool_calls:
        if tool_call.tool_name == THINK_TOOL_NAME:
            think_tool_call = tool_call
        elif tool_call.tool_name == GENERATE_REPORT_TOOL_NAME:
            generate_report_tool_call = tool_call

    return SpecialToolCalls(
        think_tool_call=think_tool_call,
        generate_report_tool_call=generate_report_tool_call,
    )
