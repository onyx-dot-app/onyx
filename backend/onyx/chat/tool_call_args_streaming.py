"""Streaming tool call argument delta emission.

LLMs stream tool call arguments as incremental raw JSON fragments (e.g.
``\\n`` as literal characters instead of actual newlines). This module
decodes the accumulated JSON value for each key and emits only the newly
decoded portion as ``ToolCallArgumentDelta`` packets so the frontend can
simply concatenate clean, displayable text.
"""

import functools
import json
import re
from collections.abc import Generator
from typing import Any
from typing import Type

from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ToolCallArgumentDelta
from onyx.tools.interface import Tool


# =============================================================================
# Tool class lookup
# =============================================================================


@functools.cache
def _get_tool_name_to_class() -> dict[str, Type[Tool]]:
    """Build a mapping from tool name (as sent to the LLM) to tool class."""
    from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP

    return {
        # All built-in tool classes expose their LLM-facing name via a
        # class-level constant (NAME or _NAME) returned by the name property.
        cls.name.fget(cls): cls  # type: ignore[union-attr]
        for cls in BUILT_IN_TOOL_MAP.values()
    }


def _get_tool_class(
    tool_calls_in_progress: dict[int, dict[str, Any]],
    tool_call_delta: Any,
) -> Type[Tool] | None:
    """Look up the Tool subclass for a streaming tool call delta.

    Returns the Tool subclass if it's a known built-in tool, or None
    for custom/MCP tools whose names are only known at runtime.
    """
    tool_name = tool_calls_in_progress.get(tool_call_delta.index, {}).get("name")
    if not tool_name:
        return None

    return _get_tool_name_to_class().get(tool_name)


# =============================================================================
# Partial JSON parsing helpers
# =============================================================================

# Matches all JSON object keys in a partial JSON string, e.g. `"code":` or `"key"  :`
# Captures the key name (group 1), handling escaped characters within keys.
_JSON_KEY_PATTERN = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*:')


def _find_active_json_key(partial_json: str) -> str | None:
    """Find the JSON key whose string value is currently being streamed.

    LLM tool calls stream arguments as incremental JSON fragments, e.g.:
        ``{"code": "print('hello')\\n...``

    This function finds all ``"key":`` patterns in the accumulated JSON and
    returns the *last* key whose value has begun arriving (i.e. there is
    content after the colon). Returns ``None`` if no value has started yet.
    """
    all_keys = _JSON_KEY_PATTERN.findall(partial_json)
    if not all_keys:
        return None

    last_key = all_keys[-1]

    # Verify this key's value has actually started (there's content after "key":)
    key_pos = partial_json.rfind(f'"{last_key}"')
    colon_pos = partial_json.find(":", key_pos)
    after_colon = partial_json[colon_pos + 1 :].lstrip() if colon_pos != -1 else ""
    if after_colon:
        return last_key

    return None


def _extract_raw_json_string_value(partial_json: str, key: str) -> str | None:
    """Extract the raw (still-escaped) string value for a given key.

    Given partial JSON like ``{"code": "line1\\nline2"}``, returns ``line1\\nline2``
    (the content between the opening and closing quotes of the value).

    If the closing quote hasn't arrived yet, returns everything after the
    opening quote. Returns ``None`` if the key's value hasn't started.
    """
    # Match the last occurrence of `"key": "` to find where the value starts
    value_opener = re.compile(r'"' + re.escape(key) + r'"\s*:\s*"')
    last_match = None
    for m in value_opener.finditer(partial_json):
        last_match = m
    if not last_match:
        return None

    value_start = last_match.end()

    # Walk forward, skipping escaped characters, to find the closing quote
    pos = value_start
    while pos < len(partial_json):
        char = partial_json[pos]
        if char == "\\":
            pos += 2  # skip the escape sequence (e.g. \n, \", \\)
        elif char == '"':
            return partial_json[value_start:pos]
        else:
            pos += 1

    # Closing quote hasn't arrived yet — return what we have so far
    return partial_json[value_start:]


def _decode_partial_json_string(raw_escaped: str) -> str:
    """Decode JSON escape sequences (e.g. ``\\n`` → newline) from a
    potentially incomplete string value.

    Wraps the raw content in quotes and uses ``json.loads`` for correct
    decoding. If the string ends mid-escape-sequence (e.g. the fragment
    ends with ``\\``), trims up to 6 trailing characters until decoding
    succeeds. The max trim of 6 covers the longest JSON escape: ``\\uXXXX``.
    """
    # Try decoding as-is first, then progressively trim trailing chars
    for chars_to_trim in range(min(7, len(raw_escaped) + 1)):
        candidate = (
            raw_escaped[: len(raw_escaped) - chars_to_trim]
            if chars_to_trim
            else raw_escaped
        )
        try:
            return json.loads('"' + candidate + '"')
        except (json.JSONDecodeError, ValueError):
            continue
    return ""


# =============================================================================
# Public API
# =============================================================================


def maybe_emit_argument_delta(
    tool_calls_in_progress: dict[int, dict[str, Any]],
    tool_call_delta: Any,
    placement: Placement,
) -> Generator[Packet, None, None]:
    """Emit decoded tool call argument content to the frontend.

    LLMs stream tool call arguments as raw JSON fragments containing escape
    sequences (e.g. ``\\n`` instead of actual newlines). This function:
    1. Determines which JSON key is currently being streamed
    2. Extracts and decodes its accumulated string value
    3. Emits only the *newly decoded* portion as a ``ToolCallArgumentDelta``

    The frontend can then simply concatenate these deltas to build clean,
    displayable content without any JSON parsing.
    """
    tool_cls = _get_tool_class(tool_calls_in_progress, tool_call_delta)
    if not tool_cls or not tool_cls.do_emit_argument_deltas():
        return

    has_new_args = tool_call_delta.function and tool_call_delta.function.arguments
    if not has_new_args:
        return

    tc_data = tool_calls_in_progress[tool_call_delta.index]
    accumulated_args = tc_data["arguments"]

    # Step 1: Find which key is actively being streamed
    active_key = _find_active_json_key(accumulated_args)
    if not active_key:
        return

    # Step 2: Extract the raw (still-escaped) string value for that key
    raw_value = _extract_raw_json_string_value(accumulated_args, active_key)
    if raw_value is None:
        return

    # Step 3: Decode escape sequences and emit only the new portion
    decoded_value = _decode_partial_json_string(raw_value)
    emitted_lengths: dict[str, int] = tc_data.setdefault("_emitted_lens", {})
    previously_emitted = emitted_lengths.get(active_key, 0)

    if len(decoded_value) <= previously_emitted:
        return

    new_content = decoded_value[previously_emitted:]
    emitted_lengths[active_key] = len(decoded_value)

    yield Packet(
        placement=placement,
        obj=ToolCallArgumentDelta(
            tool_type=tc_data.get("name", ""),
            tool_id=tc_data.get("id", ""),
            argument_deltas={active_key: new_content},
        ),
    )
