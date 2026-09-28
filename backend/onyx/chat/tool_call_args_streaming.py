from collections.abc import Generator, Mapping
from typing import Any, Type

from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet, ToolCallArgumentDelta
from onyx.tools.built_in_tools import TOOL_NAME_TO_CLASS
from onyx.tools.interface import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.streaming_json import StreamingJsonParser

logger = setup_logger()


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
    parsers: dict[int, StreamingJsonParser | None],
) -> Generator[Packet, None, None]:
    """Emit decoded tool-call argument deltas to the frontend.

    Uses a ``StreamingJsonParser`` per tool-call index to incrementally parse
    the JSON argument string and extract only the newly-appended content
    for each string-valued argument.

    NOTE: Non-string arguments (numbers, booleans, null, arrays, objects)
    are skipped — they are available in the final tool-call kickoff packet.

    ``parsers`` is a mutable dict keyed by tool-call index. A new
    ``StreamingJsonParser`` is created automatically for each new index.
    Arguments that are not valid JSON stop argument deltas for that call; the
    final tool-call kickoff still carries the raw arguments.
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
        parsers[idx] = StreamingJsonParser()
    parser = parsers[idx]
    if parser is None:
        return

    try:
        argument_deltas = parser.feed(delta_fragment)
    except ValueError:
        logger.debug("Tool arguments cannot be parsed incrementally", exc_info=True)
        parsers[idx] = None
        return

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
