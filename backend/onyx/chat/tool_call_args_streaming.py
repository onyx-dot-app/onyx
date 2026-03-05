import functools
import json
from collections.abc import Generator
from collections.abc import Mapping
from typing import Any
from typing import NamedTuple
from typing import Type

from onyx.llm.model_response import ChatCompletionDeltaToolCall
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ToolCallArgumentDelta
from onyx.tools.interface import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


@functools.cache
def _get_tool_name_to_class() -> dict[str, Type[Tool]]:
    """Build a mapping from tool name (as sent to the LLM) to tool class."""
    from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP

    result: dict[str, Type[Tool]] = {}
    for cls in BUILT_IN_TOOL_MAP.values():
        name_attr = cls.__dict__.get("name")
        if isinstance(name_attr, property) and name_attr.fget is not None:
            tool_name = name_attr.fget(cls)
        elif isinstance(name_attr, str):
            tool_name = name_attr
        else:
            continue
        result[tool_name] = cls
    return result


def _get_tool_class(
    tool_calls_in_progress: Mapping[int, Mapping[str, Any]],
    tool_call_delta: ChatCompletionDeltaToolCall,
) -> Type[Tool] | None:
    """Look up the Tool subclass for a streaming tool call delta."""
    tool_name = tool_calls_in_progress.get(tool_call_delta.index, {}).get("name")
    if not tool_name:
        return None
    return _get_tool_name_to_class().get(tool_name)


class _Token(NamedTuple):
    """A parsed JSON string with position info."""

    value: str  # raw content between the quotes
    start: int  # index of first char inside the quotes
    end: int  # index of closing quote, or len(text) if incomplete
    complete: bool  # whether the closing quote was found


def _parse_json_string(text: str, pos: int) -> _Token:
    """Parse a JSON string starting at the opening quote at ``pos``."""
    i = pos + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
        elif text[i] == '"':
            return _Token(text[pos + 1 : i], pos + 1, i, complete=True)
        else:
            i += 1
    return _Token(text[pos + 1 :], pos + 1, len(text), complete=False)


def _skip_json_value(text: str, pos: int) -> int:
    """Skip past a non-string JSON value (number, bool, null, array, object).

    Tracks ``[]`` / ``{}`` nesting depth and skips over embedded strings so
    that internal commas and braces don't terminate the scan early.  Stops
    at the next top-level ``,`` or ``}`` (not consumed).
    """
    depth = 0
    while pos < len(text):
        ch = text[pos]
        if ch == '"':
            tok = _parse_json_string(text, pos)
            pos = tok.end + 1 if tok.complete else tok.end
            continue
        if ch in ("{", "["):
            depth += 1
        elif ch in ("}", "]"):
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        pos += 1
    return pos


def _skip(text: str, pos: int, chars: str = " \t\n\r,") -> int:
    """Advance ``pos`` past any characters in ``chars``."""
    while pos < len(text) and text[pos] in chars:
        pos += 1
    return pos


def _decode_partial_json_string(raw: str) -> str:
    """Decode JSON escapes (``\\n`` → newline) from a possibly incomplete value.

    Progressively trims up to 6 trailing chars to handle partial escape
    sequences (the longest JSON escape is ``\\uXXXX``).
    """
    for trim in range(min(7, len(raw) + 1)):
        candidate = raw[: len(raw) - trim] if trim else raw
        try:
            result = json.loads('"' + candidate + '"')
            if trim > 0 and not result and raw:
                logger.warning(
                    "Dropped %d chars from partial JSON string value (trim=%d)",
                    len(raw),
                    trim,
                )
            return result
        except (json.JSONDecodeError, ValueError):
            continue
    logger.warning(
        "Failed to decode partial JSON string value; dropping %d chars", len(raw)
    )
    return ""


def _extract_delta_args(pre: str, delta: str) -> dict[str, str]:
    """Extract decoded argument values contributed by ``delta``.

    Walks ``pre + delta`` as a partial JSON object (``{"k": "v", ...}``),
    and for each string value returns only the decoded content that falls
    within the ``delta`` portion. Escape sequences that straddle the
    boundary are handled correctly.
    """
    full = pre + delta
    delta_start = len(pre)
    delta_end = len(full)

    result: dict[str, str] = {}

    # Advance to opening brace
    pos = full.find("{")
    if pos == -1:
        return result
    pos += 1

    while pos < len(full):
        pos = _skip(full, pos)
        if pos >= len(full) or full[pos] == "}":
            break

        # Key
        if full[pos] != '"':
            break
        key = _parse_json_string(full, pos)
        if not key.complete:
            break
        pos = key.end + 1

        # Colon
        pos = _skip(full, pos, " \t\n\r")
        if pos >= len(full) or full[pos] != ":":
            break
        pos += 1

        # Value
        pos = _skip(full, pos, " \t\n\r")
        if pos >= len(full):
            break
        if full[pos] != '"':
            # Non-string value (number, boolean, null, array, object):
            # skip to the next top-level comma or closing brace.
            val_start = pos
            pos = _skip_json_value(full, pos)
            # Only emit once the value is complete (delimiter found)
            # and the delimiter falls within the delta region
            if pos < len(full) and pos >= delta_start:
                raw_val = full[val_start:pos].strip()
                if raw_val:
                    result[key.value] = raw_val
            continue
        val = _parse_json_string(full, pos)

        # Only include the portion of this value that overlaps with delta
        lo = max(val.start, delta_start)
        hi = min(val.end, delta_end)
        if lo < hi:
            # Decode from value start through both boundaries so escape
            # sequences straddling the delta edge are handled correctly.
            decoded_before = _decode_partial_json_string(full[val.start : lo])
            decoded_through = _decode_partial_json_string(full[val.start : hi])
            new_content = decoded_through[len(decoded_before) :]
            if new_content:
                result[key.value] = new_content

        if not val.complete:
            break
        pos = val.end + 1

    return result


def maybe_emit_argument_delta(
    tool_calls_in_progress: Mapping[int, Mapping[str, Any]],
    tool_call_delta: ChatCompletionDeltaToolCall,
    placement: Placement,
) -> Generator[Packet, None, None]:
    """Emit decoded tool-call argument deltas to the frontend.

    Stateless: derives what's new by comparing ``accumulated_args``
    against the state before the current fragment was appended.
    """
    tool_cls = _get_tool_class(tool_calls_in_progress, tool_call_delta)
    if not tool_cls or not tool_cls.do_emit_argument_deltas():
        return

    delta_fragment = (
        tool_call_delta.function.arguments if tool_call_delta.function else None
    )
    if not delta_fragment:
        return

    tc_data = tool_calls_in_progress[tool_call_delta.index]
    accumulated_args = tc_data["arguments"]
    prev_args = accumulated_args[: -len(delta_fragment)]

    tool_type = tc_data.get("name", "")
    tool_id = tc_data.get("id", "")

    argument_deltas = _extract_delta_args(prev_args, delta_fragment)
    if not argument_deltas:
        return

    yield Packet(
        placement=placement,
        obj=ToolCallArgumentDelta(
            tool_type=tool_type,
            tool_id=tool_id,
            argument_deltas=argument_deltas,
        ),
    )
