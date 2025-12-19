import json
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import cast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onyx.chat.emitter import Emitter

from onyx.llm.models import ReasoningEffort
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.app_configs import LOG_ONYX_MODEL_INTERACTIONS
from onyx.configs.constants import MessageType
from onyx.context.search.models import SearchDoc
from onyx.file_store.models import ChatFileType
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import Delta
from onyx.llm.models import AssistantMessage
from onyx.llm.models import ChatCompletionMessage
from onyx.llm.models import FunctionCall
from onyx.llm.models import ImageContentPart
from onyx.llm.models import ImageUrlDetail
from onyx.llm.models import SystemMessage
from onyx.llm.models import TextContentPart
from onyx.llm.models import ToolCall
from onyx.llm.models import ToolMessage
from onyx.llm.models import UserMessage
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


def _parse_tool_args_to_dict(raw_args: Any) -> dict[str, Any]:
    """Parse tool arguments into a dict.

    Normal case:
    - raw_args == '{"queries":[...]}' -> dict via json.loads

    Defensive case (JSON string literal of an object):
    - raw_args == '"{\\"queries\\":[...]}"' -> json.loads -> str -> json.loads -> dict

    Anything else returns {}.
    """

    if raw_args is None:
        return {}

    if isinstance(raw_args, dict):
        return raw_args

    if not isinstance(raw_args, str):
        return {}

    try:
        parsed1: Any = json.loads(raw_args)
    except json.JSONDecodeError:
        return {}

    if isinstance(parsed1, dict):
        return parsed1

    if isinstance(parsed1, str):
        try:
            parsed2: Any = json.loads(parsed1)
        except json.JSONDecodeError:
            return {}
        return parsed2 if isinstance(parsed2, dict) else {}

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
) -> list[ToolCallKickoff]:
    """Extract ToolCallKickoff objects from the tool call map.

    Returns a list of ToolCallKickoff objects for valid tool calls (those with both id and name).
    Each tool call is assigned the given turn_index and a tab_index based on its order.
    """
    tool_calls: list[ToolCallKickoff] = []
    tab_index = 0
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
                    turn_index=turn_index,
                    tab_index=tab_index,
                )
            )
            tab_index += 1
    return tool_calls


def translate_history_to_llm_format(
    history: list[ChatMessageSimple],
) -> LanguageModelInput:
    """Convert a list of ChatMessageSimple to LanguageModelInput format.

    Converts ChatMessageSimple messages to ChatCompletionMessage format,
    handling different message types and image files for multimodal support.
    """
    messages: list[ChatCompletionMessage] = []

    for msg in history:
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
                tool_calls=tool_calls if tool_calls else None,
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

    return messages


def run_llm_step_pkt_generator(
    history: list[ChatMessageSimple],
    tool_definitions: list[dict],
    tool_choice: ToolChoiceOptions,
    llm: LLM,
    turn_index: int,
    state_container: ChatStateContainer,
    citation_processor: DynamicCitationProcessor | None,
    reasoning_effort: ReasoningEffort | None = None,
    final_documents: list[SearchDoc] | None = None,
    user_identity: LLMUserIdentity | None = None,
    custom_token_processor: (
        Callable[[Delta | None, Any], tuple[Delta | None, Any]] | None
    ) = None,
) -> Generator[Packet, None, tuple[LlmStepResult, int]]:
    # The second return value is for the turn index because reasoning counts on the frontend as a turn
    # TODO this is maybe ok but does not align well with the backend logic too well
    llm_msg_history = translate_history_to_llm_format(history)
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
        for packet in llm.stream(
            prompt=llm_msg_history,
            tools=tool_definitions,
            tool_choice=tool_choice,
            structured_response_format=None,  # TODO
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
            delta = packet.choice.delta

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
                state_container.set_reasoning_tokens(accumulated_reasoning)
                if not reasoning_start:
                    yield Packet(
                        turn_index=turn_index,
                        obj=ReasoningStart(),
                    )
                yield Packet(
                    turn_index=turn_index,
                    obj=ReasoningDelta(reasoning=delta.reasoning_content),
                )
                reasoning_start = True

            if delta.content:
                if reasoning_start:
                    yield Packet(
                        turn_index=turn_index,
                        obj=ReasoningDone(),
                    )
                    has_reasoned = 1
                    reasoning_start = False

                if not answer_start:
                    yield Packet(
                        turn_index=turn_index + has_reasoned,
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
                            state_container.set_answer_tokens(accumulated_answer)
                            yield Packet(
                                turn_index=turn_index + has_reasoned,
                                obj=AgentResponseDelta(content=result),
                            )
                        elif isinstance(result, CitationInfo):
                            yield Packet(
                                turn_index=turn_index + has_reasoned,
                                obj=result,
                            )
                else:
                    # When citation_processor is None, use delta.content directly without modification
                    accumulated_answer += delta.content
                    # Save answer incrementally to state container
                    state_container.set_answer_tokens(accumulated_answer)
                    yield Packet(
                        turn_index=turn_index + has_reasoned,
                        obj=AgentResponseDelta(content=delta.content),
                    )

            if delta.tool_calls:
                if reasoning_start:
                    yield Packet(
                        turn_index=turn_index,
                        obj=ReasoningDone(),
                    )
                    has_reasoned = 1
                    reasoning_start = False

                for tool_call_delta in delta.tool_calls:
                    _update_tool_call_with_delta(id_to_tool_call_map, tool_call_delta)

        # Flush custom token processor to get any final tool calls
        if custom_token_processor:
            flush_delta, processor_state = custom_token_processor(None, processor_state)
            if flush_delta and flush_delta.tool_calls:
                for tool_call_delta in flush_delta.tool_calls:
                    _update_tool_call_with_delta(id_to_tool_call_map, tool_call_delta)

        tool_calls = _extract_tool_call_kickoffs(
            id_to_tool_call_map, turn_index + has_reasoned
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
    # Close reasoning block if still open (stream ended with reasoning content)
    if reasoning_start:
        yield Packet(
            turn_index=turn_index,
            obj=ReasoningDone(),
        )
        has_reasoned = 1

    # Flush any remaining content from citation processor
    if citation_processor:
        for result in citation_processor.process_token(None):
            if isinstance(result, str):
                accumulated_answer += result
                # Save answer incrementally to state container
                state_container.set_answer_tokens(accumulated_answer)
                yield Packet(
                    turn_index=turn_index + has_reasoned,
                    obj=AgentResponseDelta(content=result),
                )
            elif isinstance(result, CitationInfo):
                yield Packet(
                    turn_index=turn_index + has_reasoned,
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
    emitter: "Emitter",
    history: list[ChatMessageSimple],
    tool_definitions: list[dict],
    tool_choice: ToolChoiceOptions,
    llm: LLM,
    turn_index: int,
    state_container: ChatStateContainer,
    citation_processor: DynamicCitationProcessor | None,
    reasoning_effort: ReasoningEffort | None = None,
    final_documents: list[SearchDoc] | None = None,
    user_identity: LLMUserIdentity | None = None,
    custom_token_processor: (
        Callable[[Delta | None, Any], tuple[Delta | None, Any]] | None
    ) = None,
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
        turn_index=turn_index,
        state_container=state_container,
        citation_processor=citation_processor,
        reasoning_effort=reasoning_effort,
        final_documents=final_documents,
        user_identity=user_identity,
        custom_token_processor=custom_token_processor,
    )

    while True:
        try:
            packet = next(step_generator)
            emitter.emit(packet)
        except StopIteration as e:
            llm_step_result, has_reasoned = e.value
            return llm_step_result, bool(has_reasoned)
