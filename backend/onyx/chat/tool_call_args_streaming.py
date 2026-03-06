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
from onyx.tools.built_in_tools import TOOL_NAME_TO_CLASS
from onyx.tools.interface import Tool
from onyx.utils.logger import setup_logger

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


def _extract_delta_args(
    pre: str, delta: str, scan_offset: int = 0
) -> tuple[dict[str, str], int]:
    """Extract decoded argument values contributed by ``delta``.

    Walks ``pre + delta`` as a partial JSON object (``{"k": "v", ...}``),
    and for each string value returns only the decoded content that falls
    within the ``delta`` portion. Escape sequences that straddle the
    boundary are handled correctly.

    Returns ``(argument_deltas, next_scan_offset)`` where
    ``next_scan_offset`` should be passed to the next call to skip
    completed key-value pairs, reducing cost from O(accumulated) to
    O(delta) per call.
    """
    full = pre + delta
    delta_start = len(pre)

    result: dict[str, str] = {}

    if scan_offset > 0:
        pos = scan_offset
    else:
        pos = full.find("{")
        if pos == -1:
            return result, 0
        pos += 1

    resume = pos

    while pos < len(full):
        pos = _skip(full, pos)
        if pos >= len(full) or full[pos] == "}":
            break

        resume = pos  # remember start of this key-value pair

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
            # Skip non-string values (number, boolean, null, array, object).
            # They are available in the final tool-call kickoff packet;
            # emitting them here as strings would be ambiguous for consumers
            # (e.g. the number 30 vs the string "30").
            pos = _skip_json_value(full, pos)
            continue
        val = _parse_json_string(full, pos)

        # Only include the portion of this value that overlaps with delta
        lo = max(val.start, delta_start)
        hi = val.end
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

    return result, resume


def maybe_emit_argument_delta(
    tool_calls_in_progress: Mapping[int, Mapping[str, Any]],
    tool_call_delta: ChatCompletionDeltaToolCall,
    placement: Placement,
    scan_offsets: dict[int, int],
) -> Generator[Packet, None, None]:
    """Emit decoded tool-call argument deltas to the frontend.

    NOTE: Currently skips non-string arguments

    ``scan_offsets`` is a mutable dict keyed by tool-call index that allows
    each call to skip past already-processed key-value pairs, reducing
    per-call cost from O(accumulated) to O(delta).
    """
    tool_cls = _get_tool_class(tool_calls_in_progress, tool_call_delta)
    if not tool_cls or not tool_cls.do_emit_argument_deltas():
        return

    fn = tool_call_delta.function
    delta_fragment = fn.arguments if fn else None
    if not delta_fragment:
        return

    tc_data = tool_calls_in_progress[tool_call_delta.index]
    accumulated_args = tc_data["arguments"]
    prev_args = accumulated_args[: -len(delta_fragment)]

    idx = tool_call_delta.index
    offset = scan_offsets.get(idx, 0)

    argument_deltas, new_offset = _extract_delta_args(prev_args, delta_fragment, offset)
    scan_offsets[idx] = new_offset

    if not argument_deltas:
        return

    yield Packet(
        placement=placement,
        obj=ToolCallArgumentDelta(
            tool_type=tc_data.get("name", ""),
            argument_deltas=argument_deltas,
        ),
    )
