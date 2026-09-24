"""Shared argument decoding and optional text-call compatibility parsing."""

import json
import re
import uuid
from html import unescape
from typing import Any

from onyx.llm.models import ToolCall
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string
from onyx.utils.text_processing import find_all_json_objects

logger = setup_logger()

_XML_INVOKE_BLOCK_RE = re.compile(
    r"<invoke\b(?P<attrs>[^>]*)>(?P<body>.*?)</invoke>",
    re.IGNORECASE | re.DOTALL,
)
_XML_PARAMETER_RE = re.compile(
    r"<parameter\b(?P<attrs>[^>]*)>(?P<value>.*?)</parameter>",
    re.IGNORECASE | re.DOTALL,
)


_FUNCTION_CALLS_OPEN_MARKER = "<function_calls"
_FUNCTION_CALLS_OPEN_RE = re.compile(
    r"<function_calls(?=[> \t\n\r]|\Z)", re.IGNORECASE | re.ASCII
)
_FUNCTION_CALLS_CLOSE_RE = re.compile(r"</function_calls>", re.IGNORECASE | re.ASCII)
_SPACES = " \t"


class XmlToolCallContentFilter:
    """Streaming filter that strips XML-style tool call payload blocks from text.

    Text that could be the start of a split "<function_calls" marker is held
    back until the next chunk (or flush) decides it.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._inside_block = False
        # Empty until text is emitted.
        self._last_emitted_char = ""
        # Set after a removed block so spaces after it do not double up with
        # spaces emitted before it. Line breaks are always kept.
        self._drop_spaces = False

    def process(self, content: str) -> str:
        self._pending += content
        output_parts: list[str] = []
        while True:
            if self._inside_block:
                close = _FUNCTION_CALLS_CLOSE_RE.search(self._pending)
                if close is None:
                    break
                self._pending = self._pending[close.end() :]
                self._inside_block = False
                self._drop_spaces = self._last_emitted_char in ("", *_SPACES)

            if self._drop_spaces:
                self._pending = self._pending.lstrip(_SPACES)
                if not self._pending:
                    break
                self._drop_spaces = False

            open_match = _FUNCTION_CALLS_OPEN_RE.search(self._pending)
            if open_match is not None:
                cut = open_match.start()
            else:
                # A possible marker prefix can only start at the last "<".
                cut = self._pending.rfind("<")
                if cut == -1 or not _FUNCTION_CALLS_OPEN_MARKER.startswith(
                    self._pending[cut:].lower()
                ):
                    cut = len(self._pending)

            if cut > 0:
                output_parts.append(self._pending[:cut])
                self._last_emitted_char = self._pending[cut - 1]

            if open_match is None:
                self._pending = self._pending[cut:]
                break
            self._pending = self._pending[open_match.end() :]
            self._inside_block = True

        return "".join(output_parts)

    def flush(self) -> str:
        # An incomplete block at stream end is dropped.
        remaining = "" if self._inside_block else self._pending
        self._pending = ""
        self._inside_block = False
        self._drop_spaces = False
        return remaining


def _looks_like_xml_tool_call_payload(text: str | None) -> bool:
    """Detect XML-style marshaled tool calls emitted as plain text.

    Intentionally does NOT require a <parameter> tag: zero-argument invocations
    (e.g. <function_calls><invoke name="get_time"></invoke></function_calls>) are
    valid tool calls that _extract_xml_tool_calls_from_response_text can parse, so
    requiring <parameter> would both miss them in fallback extraction and let the
    empty-answer recovery leak the raw markup as an answer.
    """
    if not text:
        return False
    lowered = text.lower()
    return "<function_calls" in lowered and "<invoke" in lowered


def extract_tool_calls_from_response_text(
    response_text: str | None,
    tool_definitions: list[dict],
) -> list[ToolCall]:
    """Extract tool calls from LLM response text by matching JSON against tool definitions.

    This is a fallback mechanism for when the LLM was expected to return tool calls
    but didn't use the proper tool call format. It searches for tool calls embedded
    in response text (JSON first, then XML-like invoke blocks) that match available
    tool definitions.

    Args:
        response_text: The LLM's text response to search for tool calls
        tool_definitions: List of tool definitions to match against

    Returns:
        List of canonical ToolCall objects for matched tools
    """
    if not response_text or not tool_definitions:
        return []

    # Build a map of tool names to their definitions
    tool_name_to_def: dict[str, dict] = {}
    for tool_def in tool_definitions:
        if tool_def.get("type") == "function" and "function" in tool_def:
            func_def = tool_def["function"]
            tool_name = func_def.get("name")
            if tool_name:
                tool_name_to_def[tool_name] = func_def

    if not tool_name_to_def:
        return []

    matched_tool_calls: list[tuple[str, dict[str, Any]]] = []
    # Find all JSON objects in the response text
    json_objects = find_all_json_objects(response_text)
    prev_json_obj: dict[str, Any] | None = None
    prev_tool_call: tuple[str, dict[str, Any]] | None = None

    for json_obj in json_objects:
        matched_tool_call = _try_match_json_to_tool(json_obj, tool_name_to_def)
        if not matched_tool_call:
            continue

        # `find_all_json_objects` can return both an outer tool-call object and
        # its nested arguments object. If both resolve to the same tool call,
        # drop only this nested duplicate artifact.
        if (
            prev_json_obj is not None
            and prev_tool_call is not None
            and matched_tool_call == prev_tool_call
            and _is_nested_arguments_duplicate(
                previous_json_obj=prev_json_obj,
                current_json_obj=json_obj,
                tool_name_to_def=tool_name_to_def,
            )
        ):
            continue

        matched_tool_calls.append(matched_tool_call)
        prev_json_obj = json_obj
        prev_tool_call = matched_tool_call

    # Some providers/models emit XML-style function calls instead of JSON objects.
    # Keep this as a fallback behind JSON extraction to preserve current behavior.
    if not matched_tool_calls:
        matched_tool_calls = _extract_xml_tool_calls_from_response_text(
            response_text=response_text,
            tool_name_to_def=tool_name_to_def,
        )

    return [
        ToolCall(id=f"extracted_{uuid.uuid4().hex[:8]}", name=name, arguments=args)
        for name, args in matched_tool_calls
    ]


def _extract_xml_tool_calls_from_response_text(
    response_text: str,
    tool_name_to_def: dict[str, dict],
) -> list[tuple[str, dict[str, Any]]]:
    """Extract XML-style tool calls from response text.

    Supports formats such as:
    <function_calls>
      <invoke name="internal_search">
        <parameter name="queries" string="false">["foo"]</parameter>
      </invoke>
    </function_calls>
    """
    matched_tool_calls: list[tuple[str, dict[str, Any]]] = []

    for invoke_match in _XML_INVOKE_BLOCK_RE.finditer(response_text):
        invoke_attrs = invoke_match.group("attrs")
        tool_name = _extract_xml_attribute(invoke_attrs, "name")
        if not tool_name or tool_name not in tool_name_to_def:
            continue

        tool_args: dict[str, Any] = {}
        invoke_body = invoke_match.group("body")
        for parameter_match in _XML_PARAMETER_RE.finditer(invoke_body):
            parameter_attrs = parameter_match.group("attrs")
            parameter_name = _extract_xml_attribute(parameter_attrs, "name")
            if not parameter_name:
                continue

            string_attr = _extract_xml_attribute(parameter_attrs, "string")
            tool_args[parameter_name] = _parse_xml_parameter_value(
                raw_value=parameter_match.group("value"),
                string_attr=string_attr,
            )

        matched_tool_calls.append((tool_name, tool_args))

    return matched_tool_calls


def _extract_xml_attribute(attrs: str, attr_name: str) -> str | None:
    """Extract a single XML-style attribute value from a tag attribute string."""
    attr_match = re.search(
        rf"""\b{re.escape(attr_name)}\s*=\s*(['"])(.*?)\1""",
        attrs,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not attr_match:
        return None
    return sanitize_string(unescape(attr_match.group(2).strip()))


def _parse_xml_parameter_value(raw_value: str, string_attr: str | None) -> Any:
    """Parse a parameter value from XML-style tool call payloads."""
    value = sanitize_string(unescape(raw_value).strip())

    if string_attr and string_attr.lower() == "true":
        return value

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _resolve_tool_arguments(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Extract and parse an arguments/parameters value from a tool-call-like object.

    Looks for "arguments" or "parameters" keys, handles JSON-string values,
    and returns a dict if successful, or None otherwise.
    """
    arguments = obj.get("arguments", obj.get("parameters", {}))
    if isinstance(arguments, str):
        arguments = sanitize_string(arguments)
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            arguments = {}
    if isinstance(arguments, dict):
        return arguments
    return None


def _try_match_json_to_tool(
    json_obj: dict[str, Any],
    tool_name_to_def: dict[str, dict],
) -> tuple[str, dict[str, Any]] | None:
    """Try to match a JSON object to a tool definition.

    Supports several formats:
    1. Direct tool call format: {"name": "tool_name", "arguments": {...}}
    2. Function call format: {"function": {"name": "tool_name", "arguments": {...}}}
    3. Tool name as key: {"tool_name": {...arguments...}}
    4. Arguments matching a tool's parameter schema

    Args:
        json_obj: The JSON object to match
        tool_name_to_def: Map of tool names to their function definitions

    Returns:
        Tuple of (tool_name, tool_args) if matched, None otherwise
    """
    # Format 1: Direct tool call format {"name": "...", "arguments": {...}}
    if "name" in json_obj and json_obj["name"] in tool_name_to_def:
        tool_name = json_obj["name"]
        arguments = _resolve_tool_arguments(json_obj)
        if arguments is not None:
            return (tool_name, arguments)

    # Format 2: Function call format {"function": {"name": "...", "arguments": {...}}}
    if "function" in json_obj and isinstance(json_obj["function"], dict):
        func_obj = json_obj["function"]
        if "name" in func_obj and func_obj["name"] in tool_name_to_def:
            tool_name = func_obj["name"]
            arguments = _resolve_tool_arguments(func_obj)
            if arguments is not None:
                return (tool_name, arguments)

    # Format 3: Tool name as key {"tool_name": {...arguments...}}
    for tool_name in tool_name_to_def:
        if tool_name in json_obj:
            arguments = json_obj[tool_name]
            if isinstance(arguments, dict):
                return (tool_name, arguments)

    # Format 4: Check if the JSON object matches a tool's parameter schema
    for tool_name, func_def in tool_name_to_def.items():
        params = func_def.get("parameters", {})
        properties = params.get("properties", {})
        required = params.get("required", [])

        if not properties:
            continue

        # Check if all required parameters are present (empty required = all optional)
        if all(req in json_obj for req in required):
            # Check if any of the tool's properties are in the JSON object
            matching_props = [prop for prop in properties if prop in json_obj]
            if matching_props:
                # Filter to only include known properties
                filtered_args = {k: v for k, v in json_obj.items() if k in properties}
                return (tool_name, filtered_args)

    return None


def _is_nested_arguments_duplicate(
    previous_json_obj: dict[str, Any],
    current_json_obj: dict[str, Any],
    tool_name_to_def: dict[str, dict],
) -> bool:
    """Detect when current object is the nested args object from previous tool call."""
    extracted_args = _extract_nested_arguments_obj(previous_json_obj, tool_name_to_def)
    return extracted_args is not None and current_json_obj == extracted_args


def _extract_nested_arguments_obj(
    json_obj: dict[str, Any],
    tool_name_to_def: dict[str, dict],
) -> dict[str, Any] | None:
    # Format 1: {"name": "...", "arguments": {...}} or {"name": "...", "parameters": {...}}
    if "name" in json_obj and json_obj["name"] in tool_name_to_def:
        args_obj = json_obj.get("arguments", json_obj.get("parameters"))
        if isinstance(args_obj, dict):
            return args_obj

    # Format 2: {"function": {"name": "...", "arguments": {...}}}
    if "function" in json_obj and isinstance(json_obj["function"], dict):
        function_obj = json_obj["function"]
        if "name" in function_obj and function_obj["name"] in tool_name_to_def:
            args_obj = function_obj.get("arguments", function_obj.get("parameters"))
            if isinstance(args_obj, dict):
                return args_obj

    # Format 3: {"tool_name": {...arguments...}}
    for tool_name in tool_name_to_def:
        if tool_name in json_obj and isinstance(json_obj[tool_name], dict):
            return json_obj[tool_name]

    return None
