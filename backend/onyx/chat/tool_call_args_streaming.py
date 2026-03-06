from collections.abc import Generator
from collections.abc import Mapping
from typing import Any
from typing import Type

from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ToolCallArgumentDelta
from onyx.tools.built_in_tools import TOOL_NAME_TO_CLASS
from onyx.tools.interface import Tool
from onyx.utils.jsonriver import Parser


def _get_tool_class(
    tool_calls_in_progress: Mapping[int, Mapping[str, Any]],
    tool_call_delta: ChatCompletionDeltaToolCall,
) -> Type[Tool] | None:
    """Look up the Tool subclass for a streaming tool call delta."""
    tool_name = tool_calls_in_progress.get(tool_call_delta.index, {}).get("name")
    if not tool_name:
        return None
    return TOOL_NAME_TO_CLASS.get(tool_name)


def maybe_emit_argument_delta(
    tool_calls_in_progress: Mapping[int, Mapping[str, Any]],
    tool_call_delta: ChatCompletionDeltaToolCall,
    placement: Placement,
    parsers: dict[int, Parser],
) -> Generator[Packet, None, None]:
    """Emit decoded tool-call argument deltas to the frontend.

    Uses a ``jsonriver.Parser`` per tool-call index to incrementally parse
    the JSON argument string and extract only the newly-appended content
    for each string-valued argument.

    NOTE: Non-string arguments (numbers, booleans, null, arrays, objects)
    are skipped — they are available in the final tool-call kickoff packet.

    ``parsers`` is a mutable dict keyed by tool-call index. A new
    ``Parser`` is created automatically for each new index.
    """
    tool_cls = _get_tool_class(tool_calls_in_progress, tool_call_delta)
    if not tool_cls or not tool_cls.should_emit_argument_deltas():
        return

    fn = tool_call_delta.function
    delta_fragment = fn.arguments if fn else None
    if not delta_fragment:
        return

    idx = tool_call_delta.index
    if idx not in parsers:
        parsers[idx] = Parser()
    parser = parsers[idx]

    deltas = parser.feed(delta_fragment)

    argument_deltas: dict[str, str] = {}
    for delta in deltas:
        if isinstance(delta, dict):
            for key, value in delta.items():
                if isinstance(value, str):
                    argument_deltas[key] = argument_deltas.get(key, "") + value

    if not argument_deltas:
        return

    tc_data = tool_calls_in_progress[tool_call_delta.index]
    yield Packet(
        placement=placement,
        obj=ToolCallArgumentDelta(
            tool_type=tc_data.get("name", ""),
            argument_deltas=argument_deltas,
        ),
    )
