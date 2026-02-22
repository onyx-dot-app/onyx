import json
import re
import time
import uuid
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Mapping
from collections.abc import Sequence
from html import unescape
from typing import Any
from typing import cast

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.app_configs import LOG_ONYX_MODEL_INTERACTIONS
from onyx.configs.app_configs import PROMPT_CACHE_CHAT_HISTORY
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import ChatFileType
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import Delta
from onyx.llm.models import AssistantMessage
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import FunctionCall
from onyx.llm.models import ImageContentPart
from onyx.llm.models import ImageUrlDetail
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import TextContentPart
from onyx.llm.models import ToolCall
from onyx.llm.models import ToolMessage
from onyx.llm.models import UserMessage
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.utils import model_needs_formatting_reenabled
from onyx.prompts.chat_prompts import CODE_BLOCK_MARKDOWN
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_CLOSE
from onyx.prompts.constants import SYSTEM_REMINDER_TAG_OPEN
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.tools.models import ToolCallKickoff
from onyx.tracing.framework.create import generation_span
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger
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
_FUNCTION_CALLS_CLOSE_MARKER = "</function_calls>"


class _XmlToolCallContentFilter:
    """Streaming filter that strips XML-style tool call payload blocks from text."""

    def __init__(self) -> None:
        self._pending = ""
        self._inside_function_calls_block = False

    def process(self, content: str) -> str:
        if not content:
            return ""

        self._pending += content
        output_parts: list[str] = []

        while self._pending:
            pending_lower = self._pending.lower()

            if self._inside_function_calls_block:
                end_idx = pending_lower.find(_FUNCTION_CALLS_CLOSE_MARKER)
                if end_idx == -1:
                    # Keep buffering until we see the close marker.
                    return "".join(output_parts)

                # Drop the whole function_calls block.
                self._pending = self._pending[
                    end_idx + len(_FUNCTION_CALLS_CLOSE_MARKER) :
                ]
                self._inside_function_calls_block = False
                continue

            start_idx = _find_function_calls_open_marker(pending_lower)
            if start_idx == -1:
                # Keep only a possible prefix of "<function_calls" in the buffer so
                # marker splits across chunks are handled correctly.
                tail_len = _matching_open_marker_prefix_len(self._pending)
                emit_upto = len(self._pending) - tail_len
                if emit_upto > 0:
                    output_parts.append(self._pending[:emit_upto])
                    self._pending = self._pending[emit_upto:]
                return "".join(output_parts)

            if start_idx > 0:
                output_parts.append(self._pending[:start_idx])

            # Enter block-stripping mode and keep scanning for close marker.
            self._pending = self._pending[start_idx:]
            self._inside_function_calls_block = True

        return "".join(output_parts)

    def flush(self) -> str:
        if self._inside_function_calls_block:
            # Drop any incomplete block at stream end.
            self._pending = ""
            self._inside_function_calls_block = False
            return ""

        remaining = self._pending
        self._pending = ""
        return remaining


def _matching_open_marker_prefix_len(text: str) -> int:
    """Return longest suffix of text that matches prefix of "<function_calls"."""
    max_len = min(len(text), len(_FUNCTION_CALLS_OPEN_MARKER) - 1)
    text_lower = text.lower()
    marker_lower = _FUNCTION_CALLS_OPEN_MARKER

    for candidate_len in range(max_len, 0, -1):
        if text_lower.endswith(marker_lower[:candidate_len]):
            return candidate_len

    return 0


def _is_valid_function_calls_open_follower(char: str | None) -> bool:
    return char is None or char in {">", " ", "\t", "\n", "\r"}


def _find_function_calls_open_marker(text_lower: str) -> int:
    """Find '<function_calls' with a valid tag boundary follower."""
    search_from = 0
    while True:
        idx = text_lower.find(_FUNCTION_CALLS_OPEN_MARKER, search_from)
        if idx == -1:
            return -1

        follower_pos = idx + len(_FUNCTION_CALLS_OPEN_MARKER)
        follower = text_lower[follower_pos] if follower_pos < len(text_lower) else None
        if _is_valid_function_calls_open_follower(follower):
            return idx

        search_from = idx + 1


def _sanitize_llm_output(value: str) -> str:
    """Remove characters that PostgreSQL's text/JSONB types cannot store.

    - NULL bytes (\x00): Not allowed in PostgreSQL text types
    - UTF-16 surrogates (\ud800-\udfff): Invalid in UTF-8 encoding
    """
    return "".join(c for c in value if c != "\x00" and not ("\ud800" <= c <= "\udfff"))


def _try_parse_json_string(value: Any) -> Any:
    """Attempt to parse a JSON string value into its Python equivalent.

    If value is a string that looks like a JSON array or object, parse it.
    Otherwise return the value unchanged.

    This handles the case where the LLM returns arguments like:
    - queries: '["query1", "query2"]' instead of ["query1", "query2"]
    """
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    # Only attempt to parse if it looks like a JSON array or object
    if not (
        (stripped.startswith("[") and stripped.endswith("]"))
        or (stripped.startswith("{") and stripped.endswith("}"))
    ):
        return value

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _parse_tool_args_to_dict(raw_args: Any) -> dict[str, Any]:
    """Parse tool arguments into a dict.

    Normal case:
    - raw_args == '{"queries":[...]}' -> dict via json.loads

    Defensive case (JSON string literal of an object):
    - raw_args == '"{\\"queries\\":[...]}"' -> json.loads -> str -> json.loads -> dict

    Also handles the case where argument values are JSON strings that need parsing:
    - {"queries": '["q1", "q2"]'} -> {"queries": ["q1", "q2"]}

    Anything else returns {}.
    """

    if raw_args is None:
        return {}

    if isinstance(raw_args, dict):
        # Parse any string values that look like JSON arrays/objects
        return {
            k: _try_parse_json_string(
                _sanitize_llm_output(v) if isinstance(v, str) else v
            )
            for k, v in raw_args.items()
        }

    if not isinstance(raw_args, str):
        return {}

    # Sanitize before parsing to remove NULL bytes and surrogates
    raw_args = _sanitize_llm_output(raw_args)

    try:
        parsed1: Any = json.loads(raw_args)
    except json.JSONDecodeError:
        return {}

    if isinstance(parsed1, dict):
        # Parse any string values that look like JSON arrays/objects
        return {k: _try_parse_json_string(v) for k, v in parsed1.items()}

    if isinstance(parsed1, str):
        try:
            parsed2: Any = json.loads(parsed1)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed2, dict):
            # Parse any string values that look like JSON arrays/objects
            return {k: _try_parse_json_string(v) for k, v in parsed2.items()}
        return {}

    return {}


def _format_message_history_for_logging(
    message_history: LanguageModelInput,
) -> str:
    """Format message history for logging, with special handling for tool calls.

    Tool calls are formatted as JSON with 4-space indentation for readability.
    """
    formatted_lines = []

    separator = "================================================"

    # Handle single ChatCompletionMessage - wrap in list for uniform processing
    if isinstance(
        message_history, (SystemMessage, UserMessage, AssistantMessage, ToolMessage)
    ):
        message_history = [message_history]

    # Handle sequence of messages
    for i, msg in enumerate(message_history):
        if isinstance(msg, SystemMessage):
            formatted_lines.append(f"Message {i + 1} [system]:")
            formatted_lines.append(separator)
            formatted_lines.append(f"{msg.content}")

        elif isinstance(msg, UserMessage):
            formatted_lines.append(f"Message {i + 1} [user]:")
            formatted_lines.append(separator)
            if isinstance(msg.content, str):
                formatted_lines.append(f"{msg.content}")
            elif isinstance(msg.content, list):
                # Handle multimodal content (text + images)
                for part in msg.content:
                    if isinstance(part, TextContentPart):
                        formatted_lines.append(f"{part.text}")
                    elif isinstance(part, ImageContentPart):
                        url = part.image_url.url
                        formatted_lines.append(f"[Image: {url[:50]}...]")

        elif isinstance(msg, AssistantMessage):
            formatted_lines.append(f"Message {i + 1} [assistant]:")
            formatted_lines.append(separator)
            if msg.content:
                formatted_lines.append(f"{msg.content}")

            if msg.tool_calls:
                formatted_lines.append("Tool calls:")
                for tool_call in msg.tool_calls:
                    tool_call_dict: dict[str, Any] = {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                    tool_call_json = json.dumps(tool_call_dict, indent=4)
                    formatted_lines.append(tool_call_json)

        elif isinstance(msg, ToolMessage):
            formatted_lines.append(f"Message {i + 1} [tool]:")
            formatted_lines.append(separator)
            formatted_lines.append(f"Tool call ID: {msg.tool_call_id}")
            formatted_lines.append(f"Response: {msg.content}")

        else:
            # Fallback for unknown message types
            formatted_lines.append(f"Message {i + 1} [unknown]:")
            formatted_lines.append(separator)
            formatted_lines.append(f"{msg}")

        # Add separator before next message (or at end)
        if i < len(message_history) - 1:
            formatted_lines.append(separator)

    return "\n".join(formatted_lines)


def _update_tool_call_with_delta(
    tool_calls_in_progress: dict[int, dict[str, Any]],
    tool_call_delta: Any,
) -> None:
    index = tool_call_delta.index

    if index not in tool_calls_in_progress:
        tool_calls_in_progress[index] = {
            # Fallback ID in case the provider never sends one via deltas.
            "id": f"fallback_{uuid.uuid4().hex}",
            "name": None,
            "arguments": "",
        }

    if tool_call_delta.id:
        tool_calls_in_progress[index]["id"] = tool_call_delta.id

    if tool_call_delta.function:
        if tool_call_delta.function.name:
            tool_calls_in_progress[index]["name"] = tool_call_delta.function.name

        if tool_call_delta.function.arguments:
            tool_calls_in_progress[index][
                "arguments"
            ] += tool_call_delta.function.arguments


def _extract_tool_call_kickoffs(
    id_to_tool_call_map: dict[int, dict[str, Any]],
    turn_index: int,
    tab_index: int | None = None,
    sub_turn_index: int | None = None,
) -> list[ToolCallKickoff]:
    """Extract ToolCallKickoff objects from the tool call map.

    Returns a list of ToolCallKickoff objects for valid tool calls (those with both id and name).
    Each tool call is assigned the given turn_index and a tab_index based on its order.

    Args:
        id_to_tool_call_map: Map of tool call index to tool call data
        turn_index: The turn index for this set of tool calls
        tab_index: If provided, use this tab_index for all tool calls (otherwise auto-increment)
        sub_turn_index: The sub-turn index for nested tool calls
    """
    tool_calls: list[ToolCallKickoff] = []
    tab_index_calculated = 0
    for tool_call_data in id_to_tool_call_map.values():
        if tool_call_data.get("id") and tool_call_data.get("name"):
            tool_args = _parse_tool_args_to_dict(tool_call_data.get("arguments"))

            tool_calls.append(
                ToolCallKickoff(
                    tool_call_id=tool_call_data["id"],
                    tool_name=tool_call_data["name"],
                    tool_args=tool_args,
                    placement=Placement(
                        turn_index=turn_index,
                        tab_index=(
                            tab_index_calculated if tab_index is None else tab_index
                        ),
                        sub_turn_index=sub_turn_index,
                    ),
                )
            )
            tab_index_calculated += 1
    return tool_calls


def extract_tool_calls_from_response_text(
    response_text: str | None,
    tool_definitions: list[dict],
    placement: Placement,
) -> list[ToolCallKickoff]:
    """Extract tool calls from LLM response text by matching JSON against tool definitions.

    This is a fallback mechanism for when the LLM was expected to return tool calls
    but didn't use the proper tool call format. It searches for tool calls embedded
    in response text (JSON first, then XML-like invoke blocks) that match available
    tool definitions.

    Args:
        response_text: The LLM's text response to search for tool calls
        tool_definitions: List of tool definitions to match against
        placement: Placement information for the tool calls

    Returns:
        List of ToolCallKickoff objects for any matched tool calls
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

    tool_calls: list[ToolCallKickoff] = []
    for tab_index, (tool_name, tool_args) in enumerate(matched_tool_calls):
        tool_calls.append(
            ToolCallKickoff(
                tool_call_id=f"extracted_{uuid.uuid4().hex[:8]}",
                tool_name=tool_name,
                tool_args=tool_args,
                placement=Placement(
                    turn_index=placement.turn_index,
                    tab_index=tab_index,
                    sub_turn_index=placement.sub_turn_index,
                ),
            )
        )

    logger.info(
        f"Extracted {len(tool_calls)} tool call(s) from response text as fallback"
    )

    return tool_calls


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
    return _sanitize_llm_output(unescape(attr_match.group(2).strip()))


def _parse_xml_parameter_value(raw_value: str, string_attr: str | None) -> Any:
    """Parse a parameter value from XML-style tool call payloads."""
    value = _sanitize_llm_output(unescape(raw_value).strip())

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


def _build_structured_assistant_message(msg: ChatMessageSimple) -> AssistantMessage:
    tool_calls_list: list[ToolCall] | None = None
    if msg.tool_calls:
        tool_calls_list = [
            ToolCall(
                id=tc.tool_call_id,
                type="function",
                function=FunctionCall(
                    name=tc.tool_name,
                    arguments=json.dumps(tc.tool_arguments),
                ),
            )
            for tc in msg.tool_calls
        ]

    return AssistantMessage(
        role="assistant",
        content=msg.message or None,
        tool_calls=tool_calls_list,
    )


def _build_structured_tool_response_message(msg: ChatMessageSimple) -> ToolMessage:
    if not msg.tool_call_id:
        raise ValueError(
            "Tool call response message encountered but tool_call_id is not available. "
            f"Message: {msg}"
        )

    return ToolMessage(
        role="tool",
        content=msg.message,
        tool_call_id=msg.tool_call_id,
    )


class _HistoryMessageFormatter:
    def format_assistant_message(self, msg: ChatMessageSimple) -> AssistantMessage:
        raise NotImplementedError

    def format_tool_response_message(
        self, msg: ChatMessageSimple
    ) -> ToolMessage | UserMessage:
        raise NotImplementedError


class _DefaultHistoryMessageFormatter(_HistoryMessageFormatter):
    def format_assistant_message(self, msg: ChatMessageSimple) -> AssistantMessage:
        return _build_structured_assistant_message(msg)

    def format_tool_response_message(self, msg: ChatMessageSimple) -> ToolMessage:
        return _build_structured_tool_response_message(msg)


class _OllamaHistoryMessageFormatter(_HistoryMessageFormatter):
    def format_assistant_message(self, msg: ChatMessageSimple) -> AssistantMessage:
        if not msg.tool_calls:
            return _build_structured_assistant_message(msg)

        tool_call_lines = [
            (
                f"[Tool Call] name={tc.tool_name} "
                f"id={tc.tool_call_id} args={json.dumps(tc.tool_arguments)}"
            )
            for tc in msg.tool_calls
        ]
        assistant_content = (
            "\n".join([msg.message, *tool_call_lines])
            if msg.message
            else "\n".join(tool_call_lines)
        )
        return AssistantMessage(
            role="assistant",
            content=assistant_content,
            tool_calls=None,
        )

    def format_tool_response_message(self, msg: ChatMessageSimple) -> UserMessage:
        if not msg.tool_call_id:
            raise ValueError(
                "Tool call response message encountered but tool_call_id is not available. "
                f"Message: {msg}"
            )

        return UserMessage(
            role="user",
            content=f"[Tool Result] id={msg.tool_call_id}\n{msg.message}",
        )


_DEFAULT_HISTORY_MESSAGE_FORMATTER = _DefaultHistoryMessageFormatter()
_OLLAMA_HISTORY_MESSAGE_FORMATTER = _OllamaHistoryMessageFormatter()


def _get_history_message_formatter(llm_config: LLMConfig) -> _HistoryMessageFormatter:
    if llm_config.model_provider == LlmProviderNames.OLLAMA_CHAT:
        return _OLLAMA_HISTORY_MESSAGE_FORMATTER

    return _DEFAULT_HISTORY_MESSAGE_FORMATTER


def translate_history_to_llm_format(
    history: list[ChatMessageSimple],
    llm_config: LLMConfig,
) -> LanguageModelInput:
    """Convert a list of ChatMessageSimple to LanguageModelInput format.

    Converts ChatMessageSimple messages to ChatCompletionMessage format,
    handling different message types and image files for multimodal support.
    """
    messages: list[ChatCompletionMessage] = []
    history_message_formatter = _get_history_message_formatter(llm_config)
    # Note: cacheability is computed from pre-translation ChatMessageSimple types.
    # Some providers flatten tool history into plain assistant/user text, so this split
    # may be less semantically meaningful, but it remains safe and order-preserving.
    last_cacheable_msg_idx = -1
    all_previous_msgs_cacheable = True

    for idx, msg in enumerate(history):
        # if the message is being added to the history
        if PROMPT_CACHE_CHAT_HISTORY and msg.message_type in [
            MessageType.SYSTEM,
            MessageType.USER,
            MessageType.USER_REMINDER,
            MessageType.ASSISTANT,
            MessageType.TOOL_CALL_RESPONSE,
        ]:
            all_previous_msgs_cacheable = (
                all_previous_msgs_cacheable and msg.should_cache
            )
            if all_previous_msgs_cacheable:
                last_cacheable_msg_idx = idx

        if msg.message_type == MessageType.SYSTEM:
            system_msg = SystemMessage(
                role="system",
                content=msg.message,
            )
            messages.append(system_msg)

        elif msg.message_type == MessageType.USER:
            # Handle user messages with potential images
            if msg.image_files:
                # Build content parts: text + images
                content_parts: list[TextContentPart | ImageContentPart] = [
                    TextContentPart(
                        type="text",
                        text=msg.message,
                    )
                ]

                # Add image parts
                for img_file in msg.image_files:
                    if img_file.file_type == ChatFileType.IMAGE:
                        try:
                            image_type = get_image_type_from_bytes(img_file.content)
                            base64_data = img_file.to_base64()
                            image_url = f"data:{image_type};base64,{base64_data}"

                            image_part = ImageContentPart(
                                type="image_url",
                                image_url=ImageUrlDetail(
                                    url=image_url,
                                    detail=None,
                                ),
                            )
                            content_parts.append(image_part)
                        except Exception as e:
                            logger.warning(
                                f"Failed to process image file {img_file.file_id}: {e}. "
                                "Skipping image."
                            )
                user_msg = UserMessage(
                    role="user",
                    content=content_parts,
                )
                messages.append(user_msg)
            else:
                # Simple text-only user message
                user_msg_text = UserMessage(
                    role="user",
                    content=msg.message,
                )
                messages.append(user_msg_text)

        elif msg.message_type == MessageType.USER_REMINDER:
            # User reminder messages are wrapped with system-reminder tags
            # and converted to UserMessage (LLM APIs don't have a native reminder type)
            wrapped_content = f"{SYSTEM_REMINDER_TAG_OPEN}\n{msg.message}\n{SYSTEM_REMINDER_TAG_CLOSE}"
            reminder_msg = UserMessage(
                role="user",
                content=wrapped_content,
            )
            messages.append(reminder_msg)

        elif msg.message_type == MessageType.ASSISTANT:
            messages.append(history_message_formatter.format_assistant_message(msg))

        elif msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            messages.append(history_message_formatter.format_tool_response_message(msg))

        else:
            logger.warning(
                f"Unknown message type {msg.message_type} in history. Skipping message."
            )

    # Apply model-specific formatting when translating to LLM format (e.g. OpenAI
    # reasoning models need CODE_BLOCK_MARKDOWN prefix for correct markdown generation)
    if model_needs_formatting_reenabled(llm_config.model_name):
        for i, m in enumerate(messages):
            if isinstance(m, SystemMessage):
                messages[i] = SystemMessage(
                    role="system",
                    content=CODE_BLOCK_MARKDOWN + m.content,
                )
                break

    # prompt caching: rely on should_cache in ChatMessageSimple to
    # pick the split point for the cacheable prefix and suffix
    if last_cacheable_msg_idx != -1:
        processed_messages, _ = process_with_prompt_cache(
            llm_config=llm_config,
            cacheable_prefix=messages[: last_cacheable_msg_idx + 1],
            suffix=messages[last_cacheable_msg_idx + 1 :],
            continuation=False,
        )
        assert isinstance(processed_messages, list)  # for mypy
        messages = processed_messages

    return messages


def _increment_turns(
    turn_index: int, sub_turn_index: int | None
) -> tuple[int, int | None]:
    if sub_turn_index is None:
        return turn_index + 1, None
    else:
        return turn_index, sub_turn_index + 1


def _delta_has_action(delta: Delta) -> bool:
    return bool(delta.content or delta.reasoning_content or delta.tool_calls)


def run_llm_step_pkt_generator(
    history: list[ChatMessageSimple],
    tool_definitions: list[dict],
    tool_choice: ToolChoiceOptions,
    llm: LLM,
    placement: Placement,
    state_container: ChatStateContainer | None,
    citation_processor: DynamicCitationProcessor | None,
    reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
    final_documents: list[SearchDoc] | None = None,
    user_identity: LLMUserIdentity | None = None,
    custom_token_processor: (
        Callable[[Delta | None, Any], tuple[Delta | None, Any]] | None
    ) = None,
    max_tokens: int | None = None,
    # TODO: Temporary handling of nested tool calls with agents, figure out a better way to handle this
    use_existing_tab_index: bool = False,
    is_deep_research: bool = False,
    pre_answer_processing_time: float | None = None,
    timeout_override: int | None = None,
) -> Generator[Packet, None, tuple[LlmStepResult, bool]]:
    """Run an LLM step and stream the response as packets.
    NOTE: DO NOT TOUCH THIS FUNCTION BEFORE ASKING YUHONG, this is very finicky and
    delicate logic that is core to the app's main functionality.

    This generator function streams LLM responses, processing reasoning content,
    answer content, tool calls, and citations. It yields Packet objects for
    real-time streaming to clients and accumulates the final result.

    Args:
        history: List of chat messages in the conversation history.
        tool_definitions: List of tool definitions available to the LLM.
        tool_choice: Tool choice configuration (e.g., "auto", "required", "none").
        llm: Language model interface to use for generation.
        placement: Placement info (turn_index, tab_index, sub_turn_index) for
            positioning packets in the conversation UI.
        state_container: Container for storing chat state (reasoning, answers).
        citation_processor: Optional processor for extracting and formatting citations
            from the response. If provided, processes tokens to identify citations.
        reasoning_effort: Optional reasoning effort configuration for models that
            support reasoning (e.g., o1 models).
        final_documents: Optional list of search documents to include in the response
            start packet.
        user_identity: Optional user identity information for the LLM.
        custom_token_processor: Optional callable that processes each token delta
            before yielding. Receives (delta, processor_state) and returns
            (modified_delta, new_processor_state). Can return None for delta to skip.
        max_tokens: Optional maximum number of tokens for the LLM response.
        use_existing_tab_index: If True, use the tab_index from placement for all
            tool calls instead of auto-incrementing.
        is_deep_research: If True, treat content before tool calls as reasoning
            when tool_choice is REQUIRED.
        pre_answer_processing_time: Optional time spent processing before the
            answer started, recorded in state_container for analytics.
        timeout_override: Optional timeout override for the LLM call.

    Yields:
        Packet: Streaming packets containing:
            - ReasoningStart/ReasoningDelta/ReasoningDone for reasoning content
            - AgentResponseStart/AgentResponseDelta for answer content
            - CitationInfo for extracted citations
            - ToolCallKickoff for tool calls (extracted at the end)

    Returns:
        tuple[LlmStepResult, bool]: A tuple containing:
            - LlmStepResult: The final result with accumulated reasoning, answer,
              and tool calls (if any).
            - bool: Whether reasoning occurred during this step. This should be used to
              increment the turn index or sub_turn index for the rest of the LLM loop.

    Note:
        The function handles incremental state updates, saving reasoning and answer
        tokens to the state container as they are generated. Tool calls are extracted
        and yielded only after the stream completes.
    """

    turn_index = placement.turn_index
    tab_index = placement.tab_index
    sub_turn_index = placement.sub_turn_index

    def _current_placement() -> Placement:
        return Placement(
            turn_index=turn_index,
            tab_index=tab_index,
            sub_turn_index=sub_turn_index,
        )

    llm_msg_history = translate_history_to_llm_format(history, llm.config)
    has_reasoned = False

    if LOG_ONYX_MODEL_INTERACTIONS:
        logger.debug(
            f"Message history:\n{_format_message_history_for_logging(llm_msg_history)}"
        )

    id_to_tool_call_map: dict[int, dict[str, Any]] = {}
    reasoning_start = False
    answer_start = False
    accumulated_reasoning = ""
    accumulated_answer = ""
    accumulated_raw_answer = ""
    xml_tool_call_content_filter = _XmlToolCallContentFilter()

    processor_state: Any = None

    with generation_span(
        model=llm.config.model_name,
        model_config={
            "base_url": str(llm.config.api_base or ""),
            "model_impl": "litellm",
        },
    ) as span_generation:
        span_generation.span_data.input = cast(
            Sequence[Mapping[str, Any]], llm_msg_history
        )
        stream_start_time = time.monotonic()
        first_action_recorded = False

        def _emit_citation_results(
            results: Generator[str | CitationInfo, None, None],
        ) -> Generator[Packet, None, None]:
            """Yield packets for citation processor results (str or CitationInfo)."""
            nonlocal accumulated_answer

            for result in results:
                if isinstance(result, str):
                    accumulated_answer += result
                    if state_container:
                        state_container.set_answer_tokens(accumulated_answer)
                    yield Packet(
                        placement=_current_placement(),
                        obj=AgentResponseDelta(content=result),
                    )
                elif isinstance(result, CitationInfo):
                    yield Packet(
                        placement=_current_placement(),
                        obj=result,
                    )
                    if state_container:
                        state_container.add_emitted_citation(result.citation_number)

        def _close_reasoning_if_active() -> Generator[Packet, None, None]:
            """Emit ReasoningDone and increment turns if reasoning is in progress."""
            nonlocal reasoning_start
            nonlocal has_reasoned
            nonlocal turn_index
            nonlocal sub_turn_index

            if reasoning_start:
                yield Packet(
                    placement=Placement(
                        turn_index=turn_index,
                        tab_index=tab_index,
                        sub_turn_index=sub_turn_index,
                    ),
                    obj=ReasoningDone(),
                )
                has_reasoned = True
                turn_index, sub_turn_index = _increment_turns(
                    turn_index, sub_turn_index
                )
                reasoning_start = False

        def _emit_content_chunk(content_chunk: str) -> Generator[Packet, None, None]:
            nonlocal accumulated_answer
            nonlocal accumulated_reasoning
            nonlocal answer_start
            nonlocal reasoning_start
            nonlocal turn_index
            nonlocal sub_turn_index

            # When tool_choice is REQUIRED, content before tool calls is reasoning/thinking
            # about which tool to call, not an actual answer to the user.
            # Treat this content as reasoning instead of answer.
            if is_deep_research and tool_choice == ToolChoiceOptions.REQUIRED:
                accumulated_reasoning += content_chunk
                if state_container:
                    state_container.set_reasoning_tokens(accumulated_reasoning)
                if not reasoning_start:
                    yield Packet(
                        placement=_current_placement(),
                        obj=ReasoningStart(),
                    )
                yield Packet(
                    placement=_current_placement(),
                    obj=ReasoningDelta(reasoning=content_chunk),
                )
                reasoning_start = True
                return

            # Normal flow for AUTO or NONE tool choice
            yield from _close_reasoning_if_active()

            if not answer_start:
                # Store pre-answer processing time in state container for save_chat
                if state_container and pre_answer_processing_time is not None:
                    state_container.set_pre_answer_processing_time(
                        pre_answer_processing_time
                    )

                yield Packet(
                    placement=_current_placement(),
                    obj=AgentResponseStart(
                        final_documents=final_documents,
                        pre_answer_processing_seconds=pre_answer_processing_time,
                    ),
                )
                answer_start = True

            if citation_processor:
                yield from _emit_citation_results(
                    citation_processor.process_token(content_chunk)
                )
            else:
                accumulated_answer += content_chunk
                # Save answer incrementally to state container
                if state_container:
                    state_container.set_answer_tokens(accumulated_answer)
                yield Packet(
                    placement=_current_placement(),
                    obj=AgentResponseDelta(content=content_chunk),
                )

        for packet in llm.stream(
            prompt=llm_msg_history,
            tools=tool_definitions,
            tool_choice=tool_choice,
            structured_response_format=None,  # TODO
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            user_identity=user_identity,
            timeout_override=timeout_override,
        ):
            if packet.usage:
                usage = packet.usage
                span_generation.span_data.usage = {
                    "input_tokens": usage.prompt_tokens,
                    "output_tokens": usage.completion_tokens,
                    "cache_read_input_tokens": usage.cache_read_input_tokens,
                    "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                }
                # Note: LLM cost tracking is now handled in multi_llm.py
            delta = packet.choice.delta

            # Weird behavior from some model providers, just log and ignore for now
            if (
                delta.content is None
                and delta.reasoning_content is None
                and delta.tool_calls is None
            ):
                logger.warning(
                    f"LLM packet is empty (no contents, reasoning or tool calls). Skipping: {packet}"
                )
                continue

            if not first_action_recorded and _delta_has_action(delta):
                span_generation.span_data.time_to_first_action_seconds = (
                    time.monotonic() - stream_start_time
                )
                first_action_recorded = True

            if custom_token_processor:
                # The custom token processor can modify the deltas for specific custom logic
                # It can also return a state so that it can handle aggregated delta logic etc.
                # Loosely typed so the function can be flexible
                modified_delta, processor_state = custom_token_processor(
                    delta, processor_state
                )
                if modified_delta is None:
                    continue
                delta = modified_delta

            # Should only happen once, frontend does not expect multiple
            # ReasoningStart or ReasoningDone packets.
            if delta.reasoning_content:
                accumulated_reasoning += delta.reasoning_content
                # Save reasoning incrementally to state container
                if state_container:
                    state_container.set_reasoning_tokens(accumulated_reasoning)
                if not reasoning_start:
                    yield Packet(
                        placement=_current_placement(),
                        obj=ReasoningStart(),
                    )
                yield Packet(
                    placement=_current_placement(),
                    obj=ReasoningDelta(reasoning=delta.reasoning_content),
                )
                reasoning_start = True

            if delta.content:
                # Keep raw content for fallback extraction. Display content can be
                # filtered and, in deep-research REQUIRED mode, routed as reasoning.
                accumulated_raw_answer += delta.content
                filtered_content = xml_tool_call_content_filter.process(delta.content)
                if filtered_content:
                    yield from _emit_content_chunk(filtered_content)

            if delta.tool_calls:
                yield from _close_reasoning_if_active()

                for tool_call_delta in delta.tool_calls:
                    _update_tool_call_with_delta(id_to_tool_call_map, tool_call_delta)

        # Flush any tail text buffered while checking for split "<function_calls" markers.
        filtered_content_tail = xml_tool_call_content_filter.flush()
        if filtered_content_tail:
            yield from _emit_content_chunk(filtered_content_tail)

        # Flush custom token processor to get any final tool calls
        if custom_token_processor:
            flush_delta, processor_state = custom_token_processor(None, processor_state)
            if (
                not first_action_recorded
                and flush_delta is not None
                and _delta_has_action(flush_delta)
            ):
                span_generation.span_data.time_to_first_action_seconds = (
                    time.monotonic() - stream_start_time
                )
                first_action_recorded = True
            if flush_delta and flush_delta.tool_calls:
                for tool_call_delta in flush_delta.tool_calls:
                    _update_tool_call_with_delta(id_to_tool_call_map, tool_call_delta)

        tool_calls = _extract_tool_call_kickoffs(
            id_to_tool_call_map=id_to_tool_call_map,
            turn_index=turn_index,
            tab_index=tab_index if use_existing_tab_index else None,
            sub_turn_index=sub_turn_index,
        )
        if tool_calls:
            tool_calls_list: list[ToolCall] = [
                ToolCall(
                    id=kickoff.tool_call_id,
                    type="function",
                    function=FunctionCall(
                        name=kickoff.tool_name,
                        arguments=json.dumps(kickoff.tool_args),
                    ),
                )
                for kickoff in tool_calls
            ]

            assistant_msg: AssistantMessage = AssistantMessage(
                role="assistant",
                content=accumulated_answer if accumulated_answer else None,
                tool_calls=tool_calls_list,
            )
            span_generation.span_data.output = [assistant_msg.model_dump()]
        elif accumulated_answer:
            assistant_msg_no_tools = AssistantMessage(
                role="assistant",
                content=accumulated_answer,
                tool_calls=None,
            )
            span_generation.span_data.output = [assistant_msg_no_tools.model_dump()]

        # Record reasoning content for tracing (extended thinking from reasoning models)
        if accumulated_reasoning:
            span_generation.span_data.reasoning = accumulated_reasoning

    # This may happen if the custom token processor is used to modify other packets into reasoning
    # Then there won't necessarily be anything else to come after the reasoning tokens
    yield from _close_reasoning_if_active()

    # Flush any remaining content from citation processor
    # Reasoning is always first so this should use the post-incremented value of turn_index
    # Note that this doesn't need to handle any sub-turns as those docs will not have citations
    # as clickable items and will be stripped out instead.
    if citation_processor:
        yield from _emit_citation_results(citation_processor.process_token(None))

    # Note: Content (AgentResponseDelta) doesn't need an explicit end packet - OverallStop handles it
    # Tool calls are handled by tool execution code and emit their own packets (e.g., SectionEnd)
    if LOG_ONYX_MODEL_INTERACTIONS:
        logger.debug(f"Accumulated reasoning: {accumulated_reasoning}")
        logger.debug(f"Accumulated answer: {accumulated_answer}")

        if tool_calls:
            tool_calls_str = "\n".join(
                f"  - {tc.tool_name}: {json.dumps(tc.tool_args, indent=4)}"
                for tc in tool_calls
            )
            logger.debug(f"Tool calls:\n{tool_calls_str}")
        else:
            logger.debug("Tool calls: []")

    return (
        LlmStepResult(
            reasoning=accumulated_reasoning if accumulated_reasoning else None,
            answer=accumulated_answer if accumulated_answer else None,
            tool_calls=tool_calls if tool_calls else None,
            raw_answer=accumulated_raw_answer if accumulated_raw_answer else None,
        ),
        has_reasoned,
    )


def run_llm_step(
    emitter: Emitter,
    history: list[ChatMessageSimple],
    tool_definitions: list[dict],
    tool_choice: ToolChoiceOptions,
    llm: LLM,
    placement: Placement,
    state_container: ChatStateContainer | None,
    citation_processor: DynamicCitationProcessor | None,
    reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
    final_documents: list[SearchDoc] | None = None,
    user_identity: LLMUserIdentity | None = None,
    custom_token_processor: (
        Callable[[Delta | None, Any], tuple[Delta | None, Any]] | None
    ) = None,
    max_tokens: int | None = None,
    use_existing_tab_index: bool = False,
    is_deep_research: bool = False,
    pre_answer_processing_time: float | None = None,
    timeout_override: int | None = None,
) -> tuple[LlmStepResult, bool]:
    """Wrapper around run_llm_step_pkt_generator that consumes packets and emits them.

    Returns:
        tuple[LlmStepResult, bool]: The LLM step result and whether reasoning occurred.
    """
    step_generator = run_llm_step_pkt_generator(
        history=history,
        tool_definitions=tool_definitions,
        tool_choice=tool_choice,
        llm=llm,
        placement=placement,
        state_container=state_container,
        citation_processor=citation_processor,
        reasoning_effort=reasoning_effort,
        final_documents=final_documents,
        user_identity=user_identity,
        custom_token_processor=custom_token_processor,
        max_tokens=max_tokens,
        use_existing_tab_index=use_existing_tab_index,
        is_deep_research=is_deep_research,
        pre_answer_processing_time=pre_answer_processing_time,
        timeout_override=timeout_override,
    )

    while True:
        try:
            packet = next(step_generator)
            emitter.emit(packet)
        except StopIteration as e:
            llm_step_result, has_reasoned = e.value
            return llm_step_result, has_reasoned
