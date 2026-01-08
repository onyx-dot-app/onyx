from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from onyx.deep_research.dr_mock_tools import GENERATE_REPORT_TOOL_NAME
from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.deep_research.models import SpecialToolCalls
from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.llm.model_response import Delta
from onyx.llm.model_response import FunctionCall
from onyx.tools.models import ToolCallKickoff


# JSON prefixes to detect in think_tool arguments
# The schema is: {"reasoning": "...content..."}
JSON_PREFIX_WITH_SPACE = '{"reasoning": "'
JSON_PREFIX_NO_SPACE = '{"reasoning":"'


class ThinkToolProcessorState(BaseModel):
    """State for tracking think tool processing across streaming deltas."""

    think_tool_found: bool = False
    think_tool_index: int | None = None
    think_tool_id: str | None = None
    full_arguments: str = ""  # Full accumulated arguments for final tool call
    accumulated_args: str = ""  # Working buffer for JSON parsing
    json_prefix_stripped: bool = False
    # Buffer holds content that might be the JSON suffix "}
    # We hold back 2 chars to avoid emitting the closing "}
    buffer: str = ""


def _unescape_json_string(s: str) -> str:
    """
    Unescape JSON string escape sequences.

    JSON strings use backslash escapes like \\n for newlines, \\t for tabs, etc.
    When we extract content from JSON by string manipulation (without json.loads),
    we need to manually decode these escape sequences.

    Note: We use a placeholder approach to handle escaped backslashes correctly.
    For example, "\\\\n" (escaped backslash + n) should become "\\n" (literal backslash + n),
    not a newline character.
    """
    # First, protect escaped backslashes with a placeholder
    placeholder = "\x00ESCAPED_BACKSLASH\x00"
    result = s.replace("\\\\", placeholder)

    # Now unescape common JSON escape sequences
    result = result.replace("\\n", "\n")
    result = result.replace("\\r", "\r")
    result = result.replace("\\t", "\t")
    result = result.replace('\\"', '"')

    # Finally, restore escaped backslashes as single backslashes
    result = result.replace(placeholder, "\\")

    return result


def _extract_reasoning_chunk(state: ThinkToolProcessorState) -> str | None:
    """
    Extract reasoning content from accumulated arguments, stripping JSON wrapper.

    Returns the next chunk of reasoning to emit, or None if nothing to emit yet.
    """
    # If we haven't found the JSON prefix yet, look for it
    if not state.json_prefix_stripped:
        # Try both prefix variants
        for prefix in [JSON_PREFIX_WITH_SPACE, JSON_PREFIX_NO_SPACE]:
            prefix_pos = state.accumulated_args.find(prefix)
            if prefix_pos != -1:
                # Found prefix - extract content after it
                content_start = prefix_pos + len(prefix)
                state.buffer = state.accumulated_args[content_start:]
                state.accumulated_args = ""
                state.json_prefix_stripped = True
                break

        if not state.json_prefix_stripped:
            # Haven't seen full prefix yet, keep accumulating
            return None
    else:
        # Already stripped prefix, add new content to buffer
        state.buffer += state.accumulated_args
        state.accumulated_args = ""

    # Hold back enough chars to avoid splitting escape sequences AND the JSON suffix "}
    # We need at least 2 for the suffix, but we also need to ensure escape sequences
    # like \n, \t, \\, \" don't get split. The longest escape is \\ (2 chars).
    # So we hold back 3 chars to be safe: if the last char is \, we don't want to
    # emit it without knowing what follows.
    holdback = 3
    if len(state.buffer) <= holdback:
        return None

    # Check if there's a trailing backslash that could be part of an escape sequence
    # If so, hold back one more character to avoid splitting the escape
    to_emit = state.buffer[:-holdback]
    remaining = state.buffer[-holdback:]

    # If to_emit ends with a backslash, it might be the start of an escape sequence
    # Move it to the remaining buffer to process with the next chunk
    # If to_emit ends with a backslash, it might be the start of an escape sequence
    # Move it to the remaining buffer to process with the next chunk
    if to_emit and to_emit[-1] == "\\":
        remaining = to_emit[-1] + remaining
        to_emit = to_emit[:-1]

    state.buffer = remaining

    # Unescape JSON escape sequences (e.g., \\n -> \n)
    if to_emit:
        to_emit = _unescape_json_string(to_emit)

    return to_emit if to_emit else None


def create_think_tool_token_processor() -> (
    Callable[[Delta | None, Any], tuple[Delta | None, Any]]
):
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
                    function=FunctionCall(
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
                    # Track full arguments for final tool call
                    state.full_arguments += tool_call.function.arguments
                    # Also accumulate for JSON parsing
                    state.accumulated_args += tool_call.function.arguments

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
