import json
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import cast

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.emitter import Emitter
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.app_configs import LOG_ONYX_MODEL_INTERACTIONS
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import ChatFileType
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
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.tools.models import TOOL_CALL_MSG_ARGUMENTS
from onyx.tools.models import TOOL_CALL_MSG_FUNC_NAME
from onyx.tools.models import ToolCallKickoff
from onyx.tracing.framework.create import generation_span
from onyx.utils.b64 import get_image_type_from_bytes
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
        return {k: _try_parse_json_string(v) for k, v in raw_args.items()}

    if not isinstance(raw_args, str):
        return {}

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

    # Handle string input
    if isinstance(message_history, str):
        formatted_lines.append("Message [string]:")
        formatted_lines.append(separator)
        formatted_lines.append(f"{message_history}")
        return "\n".join(formatted_lines)

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
            "id": None,
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
            try:
                tool_args = _parse_tool_args_to_dict(tool_call_data.get("arguments"))
            except json.JSONDecodeError:
                # If parsing fails, try empty dict, most tools would fail though
                logger.error(
                    f"Failed to parse tool call arguments: {tool_call_data['arguments']}"
                )
                tool_args = {}

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


def translate_history_to_llm_format(
    history: list[ChatMessageSimple],
    llm_config: LLMConfig,
) -> LanguageModelInput:
    """Convert a list of ChatMessageSimple to LanguageModelInput format.

    Converts ChatMessageSimple messages to ChatCompletionMessage format,
    handling different message types and image files for multimodal support.
    """
    messages: list[ChatCompletionMessage] = []
    last_cacheable_msg_idx = -1
    all_previous_msgs_cacheable = True

    for idx, msg in enumerate(history):
        # if the message is being added to the history
        if msg.message_type in [
            MessageType.SYSTEM,
            MessageType.USER,
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

        elif msg.message_type == MessageType.ASSISTANT:
            assistant_msg = AssistantMessage(
                role="assistant",
                content=msg.message or None,
                tool_calls=None,
            )
            messages.append(assistant_msg)

        elif msg.message_type == MessageType.TOOL_CALL:
            # Tool calls are represented as Assistant Messages with tool_calls field
            # Try to reconstruct tool call structure if we have tool_call_id
            tool_calls: list[ToolCall] = []
            if msg.tool_call_id:
                try:
                    # Parse the message content (which should contain function_name and arguments)
                    tool_call_data = json.loads(msg.message) if msg.message else {}

                    if (
                        isinstance(tool_call_data, dict)
                        and TOOL_CALL_MSG_FUNC_NAME in tool_call_data
                    ):
                        function_name = tool_call_data.get(
                            TOOL_CALL_MSG_FUNC_NAME, "unknown"
                        )
                        raw_args = tool_call_data.get(TOOL_CALL_MSG_ARGUMENTS, {})
                    else:
                        function_name = "unknown"
                        raw_args = (
                            tool_call_data if isinstance(tool_call_data, dict) else {}
                        )

                    # IMPORTANT: `FunctionCall.arguments` must be a JSON object string.
                    # If `raw_args` is accidentally a JSON string literal of an object
                    # (e.g. '"{\\"queries\\":[...]}"'), calling `json.dumps(raw_args)`
                    # would produce a quoted JSON literal and break Anthropic tool parsing.
                    tool_args = _parse_tool_args_to_dict(raw_args)

                    # NOTE: if the model is trained on a different tool call format, this may slightly interfere
                    # with the future tool calls, if it doesn't look like this. Almost certainly not a big deal.
                    tool_call = ToolCall(
                        id=msg.tool_call_id,
                        type="function",
                        function=FunctionCall(
                            name=function_name,
                            arguments=json.dumps(tool_args) if tool_args else "{}",
                        ),
                    )
                    tool_calls.append(tool_call)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(
                        f"Failed to parse tool call data for tool_call_id {msg.tool_call_id}: {e}. "
                        "Including as content-only message."
                    )

            assistant_msg_with_tool = AssistantMessage(
                role="assistant",
                content=None,  # The tool call is parsed, doesn't need to be duplicated in the content
                tool_calls=tool_calls or None,
            )
            messages.append(assistant_msg_with_tool)

        elif msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            if not msg.tool_call_id:
                raise ValueError(
                    f"Tool call response message encountered but tool_call_id is not available. Message: {msg}"
                )

            tool_msg = ToolMessage(
                role="tool",
                content=msg.message,
                tool_call_id=msg.tool_call_id,
            )
            messages.append(tool_msg)

        else:
            logger.warning(
                f"Unknown message type {msg.message_type} in history. Skipping message."
            )

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
    reasoning_effort: ReasoningEffort | None = None,
    final_documents: list[SearchDoc] | None = None,
    user_identity: LLMUserIdentity | None = None,
    custom_token_processor: (
        Callable[[Delta | None, Any], tuple[Delta | None, Any]] | None
    ) = None,
    max_tokens: int | None = None,
    # TODO: Temporary handling of nested tool calls with agents, figure out a better way to handle this
    use_existing_tab_index: bool = False,
    is_deep_research: bool = False,
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
        turn_index: Current turn index in the conversation.
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
        sub_turn_index: Optional sub-turn index for nested tool/agent calls.

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

    llm_msg_history = translate_history_to_llm_format(history, llm.config)
    has_reasoned = 0

    # Uncomment the line below to log the entire message history to the console
    if LOG_ONYX_MODEL_INTERACTIONS:
        logger.info(
            f"Message history:\n{_format_message_history_for_logging(llm_msg_history)}"
        )

    id_to_tool_call_map: dict[int, dict[str, Any]] = {}
    reasoning_start = False
    answer_start = False
    accumulated_reasoning = ""
    accumulated_answer = ""

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
        for packet in llm.stream(
            prompt=llm_msg_history,
            tools=tool_definitions,
            tool_choice=tool_choice,
            structured_response_format=None,  # TODO
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            user_identity=user_identity,
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
                        placement=Placement(
                            turn_index=turn_index,
                            tab_index=tab_index,
                            sub_turn_index=sub_turn_index,
                        ),
                        obj=ReasoningStart(),
                    )
                yield Packet(
                    placement=Placement(
                        turn_index=turn_index,
                        tab_index=tab_index,
                        sub_turn_index=sub_turn_index,
                    ),
                    obj=ReasoningDelta(reasoning=delta.reasoning_content),
                )
                reasoning_start = True

            if delta.content:
                # When tool_choice is REQUIRED, content before tool calls is reasoning/thinking
                # about which tool to call, not an actual answer to the user.
                # Treat this content as reasoning instead of answer.
                if is_deep_research and tool_choice == ToolChoiceOptions.REQUIRED:
                    # Treat content as reasoning when we know tool calls are coming
                    accumulated_reasoning += delta.content
                    if state_container:
                        state_container.set_reasoning_tokens(accumulated_reasoning)
                    if not reasoning_start:
                        yield Packet(
                            placement=Placement(
                                turn_index=turn_index,
                                tab_index=tab_index,
                                sub_turn_index=sub_turn_index,
                            ),
                            obj=ReasoningStart(),
                        )
                    yield Packet(
                        placement=Placement(
                            turn_index=turn_index,
                            tab_index=tab_index,
                            sub_turn_index=sub_turn_index,
                        ),
                        obj=ReasoningDelta(reasoning=delta.content),
                    )
                    reasoning_start = True
                else:
                    # Normal flow for AUTO or NONE tool choice
                    if reasoning_start:
                        yield Packet(
                            placement=Placement(
                                turn_index=turn_index,
                                tab_index=tab_index,
                                sub_turn_index=sub_turn_index,
                            ),
                            obj=ReasoningDone(),
                        )
                        has_reasoned = 1
                        turn_index, sub_turn_index = _increment_turns(
                            turn_index, sub_turn_index
                        )
                        reasoning_start = False

                    if not answer_start:
                        yield Packet(
                            placement=Placement(
                                turn_index=turn_index,
                                tab_index=tab_index,
                                sub_turn_index=sub_turn_index,
                            ),
                            obj=AgentResponseStart(
                                final_documents=final_documents,
                            ),
                        )
                        answer_start = True

                    if citation_processor:
                        for result in citation_processor.process_token(delta.content):
                            if isinstance(result, str):
                                accumulated_answer += result
                                # Save answer incrementally to state container
                                if state_container:
                                    state_container.set_answer_tokens(
                                        accumulated_answer
                                    )
                                yield Packet(
                                    placement=Placement(
                                        turn_index=turn_index,
                                        tab_index=tab_index,
                                        sub_turn_index=sub_turn_index,
                                    ),
                                    obj=AgentResponseDelta(content=result),
                                )
                            elif isinstance(result, CitationInfo):
                                yield Packet(
                                    placement=Placement(
                                        turn_index=turn_index,
                                        tab_index=tab_index,
                                        sub_turn_index=sub_turn_index,
                                    ),
                                    obj=result,
                                )
                    else:
                        # When citation_processor is None, use delta.content directly without modification
                        accumulated_answer += delta.content
                        # Save answer incrementally to state container
                        if state_container:
                            state_container.set_answer_tokens(accumulated_answer)
                        yield Packet(
                            placement=Placement(
                                turn_index=turn_index,
                                tab_index=tab_index,
                                sub_turn_index=sub_turn_index,
                            ),
                            obj=AgentResponseDelta(content=delta.content),
                        )

            if delta.tool_calls:
                if reasoning_start:
                    yield Packet(
                        placement=Placement(
                            turn_index=turn_index,
                            tab_index=tab_index,
                            sub_turn_index=sub_turn_index,
                        ),
                        obj=ReasoningDone(),
                    )
                    has_reasoned = 1
                    turn_index, sub_turn_index = _increment_turns(
                        turn_index, sub_turn_index
                    )
                    reasoning_start = False

                for tool_call_delta in delta.tool_calls:
                    _update_tool_call_with_delta(id_to_tool_call_map, tool_call_delta)

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

    # This may happen if the custom token processor is used to modify other packets into reasoning
    # Then there won't necessarily be anything else to come after the reasoning tokens
    if reasoning_start:
        yield Packet(
            placement=Placement(
                turn_index=turn_index,
                tab_index=tab_index,
                sub_turn_index=sub_turn_index,
            ),
            obj=ReasoningDone(),
        )
        has_reasoned = 1
        turn_index, sub_turn_index = _increment_turns(turn_index, sub_turn_index)
        reasoning_start = False

    # Flush any remaining content from citation processor
    # Reasoning is always first so this should use the post-incremented value of turn_index
    # Note that this doesn't need to handle any sub-turns as those docs will not have citations
    # as clickable items and will be stripped out instead.
    if citation_processor:
        for result in citation_processor.process_token(None):
            if isinstance(result, str):
                accumulated_answer += result
                # Save answer incrementally to state container
                if state_container:
                    state_container.set_answer_tokens(accumulated_answer)
                yield Packet(
                    placement=Placement(
                        turn_index=turn_index,
                        tab_index=tab_index,
                        sub_turn_index=sub_turn_index,
                    ),
                    obj=AgentResponseDelta(content=result),
                )
            elif isinstance(result, CitationInfo):
                yield Packet(
                    placement=Placement(
                        turn_index=turn_index,
                        tab_index=tab_index,
                        sub_turn_index=sub_turn_index,
                    ),
                    obj=result,
                )

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
        ),
        bool(has_reasoned),
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
    reasoning_effort: ReasoningEffort | None = None,
    final_documents: list[SearchDoc] | None = None,
    user_identity: LLMUserIdentity | None = None,
    custom_token_processor: (
        Callable[[Delta | None, Any], tuple[Delta | None, Any]] | None
    ) = None,
    max_tokens: int | None = None,
    use_existing_tab_index: bool = False,
    is_deep_research: bool = False,
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
    )

    while True:
        try:
            packet = next(step_generator)
            emitter.emit(packet)
        except StopIteration as e:
            llm_step_result, has_reasoned = e.value
            return llm_step_result, bool(has_reasoned)
