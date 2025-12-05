import json
from collections.abc import Generator
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Any
from typing import cast

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.citation_processor import DynamicCitationProcessor
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import LlmStepResult
from onyx.configs.app_configs import LOG_ONYX_MODEL_INTERACTIONS
from onyx.context.search.models import SearchDoc
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ToolCall
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningDone
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.tools.models import ToolCallKickoff
from onyx.tracing.framework.create import generation_span
from onyx.utils.logger import setup_logger

logger = setup_logger()


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
) -> list[ToolCallKickoff]:
    """Extract ToolCallKickoff objects from the tool call map.

    Returns a list of ToolCallKickoff objects for valid tool calls (those with both id and name).
    """
    tool_calls: list[ToolCallKickoff] = []
    for tool_call_data in id_to_tool_call_map.values():
        if tool_call_data.get("id") and tool_call_data.get("name"):
            try:
                # Parse arguments JSON string to dict
                tool_args = (
                    json.loads(tool_call_data["arguments"])
                    if tool_call_data["arguments"]
                    else {}
                )
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
                )
            )
    return tool_calls


def run_llm_step(
    history: list[ChatMessageSimple],
    tool_definitions: list[dict],
    tool_choice: ToolChoiceOptions,
    llm: LLM,
    turn_index: int,
    citation_processor: DynamicCitationProcessor,
    state_container: ChatStateContainer,
    final_documents: list[SearchDoc] | None = None,
) -> Generator[Packet, None, tuple[LlmStepResult, int]]:
    """Run a single LLM step, yielding packets and returning the result.

    This is a generator that yields Packet objects for streaming responses
    and returns a tuple of (LlmStepResult, turn_index) when complete.

    Args:
        history: The message history to send to the LLM
        tool_definitions: Tool definitions for the LLM
        tool_choice: Tool choice option ("auto", "none", "required")
        llm: The LLM instance to use
        turn_index: Current turn index
        citation_processor: Processor for handling citations
        state_container: Container for chat state
        final_documents: Optional list of final documents for citations

    Yields:
        Packet objects containing reasoning, response, or citation data

    Returns:
        Tuple of (LlmStepResult, updated turn_index)
    """
    from onyx.chat.llm_loop import translate_history_to_llm_format
    from onyx.chat.llm_loop import _format_message_history_for_logging

    # The second return value is for the turn index because reasoning counts on the frontend as a turn
    llm_msg_history = translate_history_to_llm_format(history)

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
                    turn_index += 1
                    reasoning_start = False

                if not answer_start:
                    yield Packet(
                        turn_index=turn_index,
                        obj=AgentResponseStart(
                            final_documents=final_documents,
                        ),
                    )
                    answer_start = True

                for result in citation_processor.process_token(delta.content):
                    if isinstance(result, str):
                        accumulated_answer += result
                        # Save answer incrementally to state container
                        state_container.set_answer_tokens(accumulated_answer)
                        yield Packet(
                            turn_index=turn_index,
                            obj=AgentResponseDelta(content=result),
                        )
                    elif isinstance(result, CitationInfo):
                        yield Packet(
                            turn_index=turn_index,
                            obj=result,
                        )

            if delta.tool_calls:
                if reasoning_start:
                    yield Packet(
                        turn_index=turn_index,
                        obj=ReasoningDone(),
                    )
                    turn_index += 1
                    reasoning_start = False

                for tool_call_delta in delta.tool_calls:
                    _update_tool_call_with_delta(id_to_tool_call_map, tool_call_delta)

        tool_calls = _extract_tool_call_kickoffs(id_to_tool_call_map)
        if tool_calls:
            tool_calls_list: list[ToolCall] = [
                {
                    "id": kickoff.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": kickoff.tool_name,
                        "arguments": json.dumps(kickoff.tool_args),
                    },
                }
                for kickoff in tool_calls
            ]

            assistant_msg: AssistantMessage = {
                "role": "assistant",
                "content": accumulated_answer if accumulated_answer else None,
                "tool_calls": tool_calls_list,
            }
            span_generation.span_data.output = [assistant_msg]
        elif accumulated_answer:
            span_generation.span_data.output = [
                {"role": "assistant", "content": accumulated_answer}
            ]
    # Close reasoning block if still open (stream ended with reasoning content)
    if reasoning_start:
        yield Packet(
            turn_index=turn_index,
            obj=ReasoningDone(),
        )
        turn_index += 1

    # Flush any remaining content from citation processor
    if citation_processor:
        for result in citation_processor.process_token(None):
            if isinstance(result, str):
                accumulated_answer += result
                # Save answer incrementally to state container
                state_container.set_answer_tokens(accumulated_answer)
                yield Packet(
                    turn_index=turn_index,
                    obj=AgentResponseDelta(content=result),
                )
            elif isinstance(result, CitationInfo):
                yield Packet(
                    turn_index=turn_index,
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
        turn_index,
    )
