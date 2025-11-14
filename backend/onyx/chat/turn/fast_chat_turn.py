from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from uuid import UUID

from agents import Agent
from agents import RawResponsesStreamEvent
from agents import RunResultStreaming
from agents import ToolCallItem
from agents.tracing import trace

from onyx.agents.agent_framework.models import ModelResponseStream
from onyx.agents.agent_framework.models import RunItemStreamEvent
from onyx.agents.agent_framework.query import query
from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import InputTextContent
from onyx.agents.agent_sdk.message_types import SystemMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.agents.agent_sdk.monkey_patches import (
    monkey_patch_convert_tool_choice_to_ignore_openai_hosted_web_search,
)
from onyx.agents.agent_sdk.sync_agent_stream_adapter import SyncAgentStream
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.chat.chat_utils import llm_docs_from_fetched_documents_cache
from onyx.chat.chat_utils import saved_search_docs_from_llm_docs
from onyx.chat.memories import get_memories
from onyx.chat.models import PromptConfig
from onyx.chat.packet_sniffing import has_had_message_start
from onyx.chat.prompt_builder.answer_prompt_builder import (
    default_build_system_message_v2,
)
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.stop_signal_checker import reset_cancel_status
from onyx.chat.stream_processing.citation_processing import CitationProcessor
from onyx.chat.stream_processing.utils import map_document_id_order_v2
from onyx.chat.turn.context_handler.citation import (
    assign_citation_numbers_recent_tool_calls,
)
from onyx.chat.turn.context_handler.reminder import maybe_append_reminder
from onyx.chat.turn.infra.chat_turn_event_stream import unified_event_stream
from onyx.chat.turn.models import AgentToolType
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.chat.turn.prompts.custom_instruction import build_custom_instructions
from onyx.chat.turn.save_turn import extract_final_answer_from_packets
from onyx.chat.turn.save_turn import save_turn
from onyx.llm.message_types import AssistantMessage
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.message_types import ToolMessage
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketObj
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.adapter_v1_to_v2 import force_use_tool_to_function_tool_names
from onyx.tools.adapter_v1_to_v2 import tools_to_function_tools
from onyx.tools.force import ForceUseTool
from onyx.tools.tool import Tool

if TYPE_CHECKING:
    from litellm import ResponseFunctionToolCall

MAX_ITERATIONS = 10


# TODO -- this can be refactored out and played with in evals + normal demo
def _run_agent_loop(
    messages: list[AgentSDKMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    ctx: ChatTurnContext,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
) -> None:
    monkey_patch_convert_tool_choice_to_ignore_openai_hosted_web_search()
    # This should have already been called, but call it again here for good measure.
    # TODO: Get to the root of why sometimes it seems litellm settings aren't configured.
    from onyx.llm.litellm_singleton.config import initialize_litellm

    initialize_litellm()
    chat_history = messages[1:-1]
    current_user_message = cast(UserMessage, messages[-1])
    agent_turn_messages: list[AgentSDKMessage] = []
    last_call_is_final = False
    iteration_count = 0

    while not last_call_is_final:
        available_tools: Sequence[Tool] = (
            dependencies.tools if iteration_count < MAX_ITERATIONS else []
        )
        memories = get_memories(dependencies.user_or_none, dependencies.db_session)
        # TODO: The system is rather prompt-cache efficient except for rebuilding the system prompt.
        # The biggest offender is when we hit max iterations and then all the tool calls cannot
        # be cached anymore since the system message will be differ in that it will have no tools.
        langchain_system_message = default_build_system_message_v2(
            dependencies.prompt_config,
            dependencies.llm.config,
            memories,
            available_tools,
            ctx.should_cite_documents,
        )
        new_system_prompt = SystemMessage(
            role="system",
            content=[
                InputTextContent(
                    type="input_text", text=str(langchain_system_message.content)
                )
            ],
        )
        custom_instructions = build_custom_instructions(prompt_config)
        previous_messages = (
            [new_system_prompt]
            + chat_history
            + custom_instructions
            + [current_user_message]
        )
        current_messages = previous_messages + agent_turn_messages

        if not available_tools:
            tool_choice = None
        else:
            tool_choice = (
                force_use_tool_to_function_tool_names(force_use_tool, available_tools)
                if iteration_count == 0 and force_use_tool
                else None
            ) or "auto"

        model_settings = replace(dependencies.model_settings, tool_choice=tool_choice)

        agent = Agent(
            name="Assistant",
            model=dependencies.llm_model,
            tools=cast(list[AgentToolType], tools_to_function_tools(available_tools)),
            model_settings=model_settings,
            tool_use_behavior="stop_on_first_tool",
        )
        agent_stream: SyncAgentStream = SyncAgentStream(
            agent=agent,
            input=current_messages,
            context=ctx,
        )
        streamed, tool_call_events = _process_stream(
            agent_stream, chat_session_id, dependencies, ctx
        )

        all_messages_after_stream = streamed.to_input_list()
        agent_turn_messages = [
            cast(AgentSDKMessage, msg)
            for msg in all_messages_after_stream[len(previous_messages) :]
        ]

        # Apply context handlers in order:
        # 1. Remove all user messages in the middle (previous reminders)
        agent_turn_messages = [
            msg for msg in agent_turn_messages if msg.get("role") != "user"
        ]

        # 2. Add task prompt reminder
        last_iteration_included_web_search = any(
            tool_call.name == "web_search" for tool_call in tool_call_events
        )
        agent_turn_messages = maybe_append_reminder(
            agent_turn_messages,
            prompt_config,
            ctx.should_cite_documents,
            last_iteration_included_web_search,
        )

        # 3. Assign citation numbers to tool call outputs
        # Instead of doing this complex parsing from the tool call response,
        # I could have just used the ToolCallOutput event from the Agents SDK.
        # TODO: When agent framework is gone, I can just use our ToolCallOutput event.
        citation_result = assign_citation_numbers_recent_tool_calls(
            agent_turn_messages, ctx
        )
        agent_turn_messages = list(citation_result.updated_messages)
        ctx.documents_processed_by_citation_context_handler += (
            citation_result.new_docs_cited
        )
        ctx.tool_calls_processed_by_citation_context_handler += (
            citation_result.num_tool_calls_cited
        )

        # TODO: Make this configurable on OnyxAgent level
        stopping_tools = ["image_generation"]
        if len(tool_call_events) == 0 or any(
            tool.name in stopping_tools for tool in tool_call_events
        ):
            last_call_is_final = True
        iteration_count += 1


def _run_agent_loop_v2(
    messages: list[ChatCompletionMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    ctx: ChatTurnContext,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
) -> None:
    """Refactored agent loop using new query interface and ChatCompletionMessage format.

    This version dramatically simplifies packet processing by using the query() function
    which handles reasoning start/stop events automatically.
    """
    # This should have already been called, but call it again here for good measure.
    from onyx.llm.litellm_singleton.config import initialize_litellm

    initialize_litellm()

    chat_history = messages[1:-1]
    current_user_message = messages[-1]

    agent_turn_messages: list[ChatCompletionMessage] = []
    last_call_is_final = False
    iteration_count = 0

    while not last_call_is_final:
        available_tools: Sequence[Tool] = (
            dependencies.tools if iteration_count < MAX_ITERATIONS else []
        )

        memories = get_memories(dependencies.user_or_none, dependencies.db_session)

        # Build system message
        langchain_system_message = default_build_system_message_v2(
            dependencies.prompt_config,
            dependencies.llm.config,
            memories,
            available_tools,
            ctx.should_cite_documents,
        )

        new_system_message: ChatCompletionMessage = {
            "role": "system",
            "content": str(langchain_system_message.content),
        }

        # Build custom instructions as user messages
        custom_instructions: list[ChatCompletionMessage] = []
        if prompt_config.custom_instructions:
            custom_instructions.append(
                {
                    "role": "user",
                    "content": f"Custom Instructions: {prompt_config.custom_instructions}",
                }
            )

        # Construct full message list
        previous_messages = (
            [new_system_message]
            + chat_history
            + custom_instructions
            + [current_user_message]
        )
        current_messages = previous_messages + agent_turn_messages

        # Determine tool choice
        if not available_tools:
            tool_choice = None
        else:
            tool_choice = (
                force_use_tool_to_function_tool_names(force_use_tool, available_tools)
                if iteration_count == 0 and force_use_tool
                else None
            ) or "auto"

        # Process the stream from query()
        assistant_content = ""
        tool_calls_dict: dict[str, dict[str, Any]] = {}
        tool_call_outputs: dict[str, str] = {}
        reasoning_content = ""

        for event in query(
            llm_with_default_settings=dependencies.llm,
            messages=current_messages,
            tools=available_tools,
            context=ctx,
            tool_choice=tool_choice,
        ):
            # Check for cancellation
            connected = is_connected(
                chat_session_id,
                dependencies.redis_client,
            )
            if not connected:
                _emit_clean_up_packets(dependencies, ctx)
                break

            # Process the event
            if isinstance(event, RunItemStreamEvent):
                # Handle structured events
                if event.type == "reasoning_start":
                    dependencies.emitter.emit(
                        Packet(ind=ctx.current_run_step, obj=ReasoningStart())
                    )
                    reasoning_content = ""
                elif event.type == "reasoning_done":
                    ctx.current_run_step += 1
                    dependencies.emitter.emit(
                        Packet(
                            ind=ctx.current_run_step, obj=SectionEnd(type="section_end")
                        )
                    )
                elif event.type == "message_start":
                    llm_docs_for_message_start = llm_docs_from_fetched_documents_cache(
                        ctx.fetched_documents_cache
                    )
                    retrieved_search_docs = saved_search_docs_from_llm_docs(
                        llm_docs_for_message_start
                    )
                    ctx.current_run_step += 1
                    dependencies.emitter.emit(
                        Packet(
                            ind=ctx.current_run_step,
                            obj=MessageStart(
                                content="", final_documents=retrieved_search_docs
                            ),
                        )
                    )
                elif event.type == "message_done":
                    dependencies.emitter.emit(
                        Packet(
                            ind=ctx.current_run_step, obj=SectionEnd(type="section_end")
                        )
                    )
                elif event.type == "tool_call" and event.details:
                    tool_call_item = event.details
                    if tool_call_item.call_id and tool_call_item.name:
                        tool_calls_dict[tool_call_item.call_id] = {
                            "id": tool_call_item.call_id,
                            "type": "function",
                            "function": {
                                "name": tool_call_item.name,
                                "arguments": tool_call_item.arguments or "",
                            },
                        }
                elif event.type == "tool_call_output" and event.details:
                    output_item = event.details
                    if output_item.call_id:
                        tool_call_outputs[output_item.call_id] = str(output_item.output)

            elif isinstance(event, ModelResponseStream):
                # Handle raw model response chunks
                delta = event.choice.delta

                if delta.reasoning_content:
                    reasoning_content += delta.reasoning_content
                    dependencies.emitter.emit(
                        Packet(
                            ind=ctx.current_run_step,
                            obj=ReasoningDelta(reasoning=delta.reasoning_content),
                        )
                    )

                if delta.content:
                    # Process content through citation processor if available
                    llm_docs = llm_docs_from_fetched_documents_cache(
                        ctx.fetched_documents_cache
                    )
                    if llm_docs:
                        mapping = map_document_id_order_v2(llm_docs)
                        processor = CitationProcessor(
                            context_docs=llm_docs,
                            doc_id_to_rank_map=mapping,
                            stop_stream=None,
                        )
                        final_answer_piece = ""
                        for response_part in processor.process_token(delta.content):
                            if isinstance(response_part, CitationInfo):
                                ctx.citations.append(response_part)
                            else:
                                final_answer_piece += response_part.answer_piece or ""
                        assistant_content += final_answer_piece
                        dependencies.emitter.emit(
                            Packet(
                                ind=ctx.current_run_step,
                                obj=MessageDelta(content=final_answer_piece),
                            )
                        )
                    else:
                        assistant_content += delta.content
                        dependencies.emitter.emit(
                            Packet(
                                ind=ctx.current_run_step,
                                obj=MessageDelta(content=delta.content),
                            )
                        )

        # Build new messages from this iteration
        new_messages: list[ChatCompletionMessage] = []

        # Add assistant message (either with content or tool calls)
        if tool_calls_dict:
            # Assistant made tool calls
            tool_calls_list = list(tool_calls_dict.values())
            assistant_msg: AssistantMessage = {
                "role": "assistant",
                "content": assistant_content if assistant_content else None,
                "tool_calls": tool_calls_list,
            }
            new_messages.append(assistant_msg)

            # Add tool response messages
            for tool_call in tool_calls_list:
                call_id = tool_call["id"]
                if call_id in tool_call_outputs:
                    tool_msg: ToolMessage = {
                        "role": "tool",
                        "content": tool_call_outputs[call_id],
                        "tool_call_id": call_id,
                    }
                    new_messages.append(tool_msg)
        elif assistant_content:
            # Assistant responded with text
            assistant_msg: AssistantMessage = {
                "role": "assistant",
                "content": assistant_content,
            }
            new_messages.append(assistant_msg)

        # Apply context handlers
        # TODO: Port context handlers to work with ChatCompletionMessage format
        # For now, track iteration metrics
        agent_turn_messages.extend(new_messages)

        # Determine if we should continue
        # TODO: Make this configurable on OnyxAgent level
        stopping_tools = ["image_generation"]
        if not tool_calls_dict or any(
            tc["function"]["name"] in stopping_tools for tc in tool_calls_dict.values()
        ):
            last_call_is_final = True

        iteration_count += 1


def _fast_chat_turn_core(
    messages: list[ChatCompletionMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
    # Dependency injectable argument for testing
    starter_context: ChatTurnContext | None = None,
) -> None:
    """Core fast chat turn logic that allows overriding global_iteration_responses for testing.

    Args:
        messages: List of chat messages in ChatCompletionMessage format
        dependencies: Chat turn dependencies
        chat_session_id: Chat session ID
        message_id: Message ID
        research_type: Research type
        starter_context: Optional starter context for testing
    """
    reset_cancel_status(
        chat_session_id,
        dependencies.redis_client,
    )
    ctx = starter_context or ChatTurnContext(
        run_dependencies=dependencies,
        chat_session_id=chat_session_id,
        message_id=message_id,
        research_type=research_type,
    )
    with trace("fast_chat_turn"):
        _run_agent_loop_v2(
            messages=messages,
            dependencies=dependencies,
            chat_session_id=chat_session_id,
            ctx=ctx,
            prompt_config=prompt_config,
            force_use_tool=force_use_tool,
        )
    _emit_citations_for_final_answer(
        dependencies=dependencies,
        ctx=ctx,
    )
    final_answer = extract_final_answer_from_packets(
        dependencies.emitter.packet_history
    )
    # TODO: Make this error handling more robust and not so specific to the qwen ollama cloud case
    # where if it happens to any cloud questions, it hangs on read url
    has_image_generation = any(
        packet.obj.type == "image_generation_tool_delta"
        for packet in dependencies.emitter.packet_history
    )
    # Allow empty final answer if image generation tool was used (it produces images, not text)
    if len(final_answer) == 0 and not has_image_generation:
        raise ValueError(
            """Final answer is empty. Inference provider likely failed to provide
            content packets.
            """
        )
    save_turn(
        db_session=dependencies.db_session,
        message_id=message_id,
        chat_session_id=chat_session_id,
        research_type=research_type,
        model_name=dependencies.llm.config.model_name,
        model_provider=dependencies.llm.config.model_provider,
        iteration_instructions=ctx.iteration_instructions,
        global_iteration_responses=ctx.global_iteration_responses,
        final_answer=final_answer,
        fetched_documents_cache=ctx.fetched_documents_cache,
    )
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=OverallStop(type="stop"))
    )


@unified_event_stream
def fast_chat_turn(
    messages: list[ChatCompletionMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
) -> None:
    _fast_chat_turn_core(
        messages,
        dependencies,
        chat_session_id,
        message_id,
        research_type,
        prompt_config,
        force_use_tool=force_use_tool,
    )


def _process_stream(
    agent_stream: SyncAgentStream,
    chat_session_id: UUID,
    dependencies: ChatTurnDependencies,
    ctx: ChatTurnContext,
) -> tuple[RunResultStreaming, list["ResponseFunctionToolCall"]]:
    from litellm import ResponseFunctionToolCall

    llm_docs = llm_docs_from_fetched_documents_cache(ctx.fetched_documents_cache)
    mapping = map_document_id_order_v2(llm_docs)
    if llm_docs:
        processor = CitationProcessor(
            context_docs=llm_docs,
            doc_id_to_rank_map=mapping,
            stop_stream=None,
        )
    else:
        processor = None
    tool_call_events: list[ResponseFunctionToolCall] = []
    for ev in agent_stream:
        connected = is_connected(
            chat_session_id,
            dependencies.redis_client,
        )
        if not connected:
            _emit_clean_up_packets(dependencies, ctx)
            agent_stream.cancel()
            break
        packets = _default_packet_translation(
            ev, ctx, processor, dependencies.emitter.packet_history
        )
        for packet in packets:
            dependencies.emitter.emit(packet)
        if isinstance(getattr(ev, "item", None), ToolCallItem):
            tool_call_events.append(cast(ResponseFunctionToolCall, ev.item.raw_item))
    if agent_stream.streamed is None:
        raise ValueError("agent_stream.streamed is None")
    return agent_stream.streamed, tool_call_events


# TODO: Maybe in general there's a cleaner way to handle cancellation in the middle of a tool call?
def _emit_clean_up_packets(
    dependencies: ChatTurnDependencies, ctx: ChatTurnContext
) -> None:
    if not (
        dependencies.emitter.packet_history
        and dependencies.emitter.packet_history[-1].obj.type == "message_delta"
    ):
        dependencies.emitter.emit(
            Packet(
                ind=ctx.current_run_step,
                obj=MessageStart(
                    type="message_start", content="Cancelled", final_documents=None
                ),
            )
        )
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=SectionEnd(type="section_end"))
    )


def _emit_citations_for_final_answer(
    dependencies: ChatTurnDependencies,
    ctx: ChatTurnContext,
) -> None:
    index = ctx.current_run_step + 1
    if ctx.citations:
        dependencies.emitter.emit(Packet(ind=index, obj=CitationStart()))
        dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=CitationDelta(citations=ctx.citations),
            )
        )
        dependencies.emitter.emit(Packet(ind=index, obj=SectionEnd(type="section_end")))
    ctx.current_run_step = index


def _default_packet_translation(
    ev: object,
    ctx: ChatTurnContext,
    processor: CitationProcessor | None,
    packet_history: list[Packet],
) -> list[Packet]:
    """Function is a bit messy atm, since there's a bug in OpenAI Agents SDK that
    causes Anthropic packets to be out of order.

    TODO (chris): clean this up once OpenAI Agents SDK is fixed.
    """

    # lazy loading to save memory
    from openai.types.responses import ResponseReasoningSummaryPartAddedEvent
    from openai.types.responses import ResponseReasoningSummaryPartDoneEvent
    from openai.types.responses import ResponseReasoningSummaryTextDeltaEvent

    packets: list[Packet] = []
    obj: PacketObj | None = None
    if isinstance(ev, RawResponsesStreamEvent):
        output_index = getattr(ev.data, "output_index", None)

        # ------------------------------------------------------------
        # Reasoning packets
        # ------------------------------------------------------------
        if isinstance(ev.data, ResponseReasoningSummaryPartAddedEvent):
            packets.append(Packet(ind=ctx.current_run_step, obj=ReasoningStart()))
            ctx.current_output_index = output_index
        elif isinstance(ev.data, ResponseReasoningSummaryTextDeltaEvent):
            packets.append(
                Packet(
                    ind=ctx.current_run_step,
                    obj=ReasoningDelta(reasoning=ev.data.delta),
                )
            )
        elif isinstance(ev.data, ResponseReasoningSummaryPartDoneEvent):
            # only do anything if we haven't already "gone past" this step
            # (e.g. if we've already sent the MessageStart / MessageDelta packets, then we
            # shouldn't do anything)
            if ctx.current_output_index == output_index:
                ctx.current_run_step += 1
                ctx.current_output_index = None
                packets.append(Packet(ind=ctx.current_run_step, obj=SectionEnd()))

        # ------------------------------------------------------------
        # Message packets
        # ------------------------------------------------------------

        # TODO: add this back in. We'd like this to be a simple, dumb translation layer
        # but we can't do that right now since there are weird provider behavior w/ empty
        # `response.content_part.added` packets
        # elif ev.data.type == "response.content_part.added":
        #     retrieved_search_docs = saved_search_docs_from_llm_docs(
        #         ctx.ordered_fetched_documents
        #     )
        #     obj = MessageStart(content="", final_documents=retrieved_search_docs)
        elif ev.data.type == "response.output_text.delta" and len(ev.data.delta) > 0:
            if processor:
                final_answer_piece = ""
                for response_part in processor.process_token(ev.data.delta):
                    if isinstance(response_part, CitationInfo):
                        ctx.citations.append(response_part)
                    else:
                        final_answer_piece += response_part.answer_piece or ""
                obj = MessageDelta(content=final_answer_piece)
            else:
                obj = MessageDelta(content=ev.data.delta)

            needs_start = has_had_message_start(packet_history, ctx.current_run_step)
            if needs_start:
                ctx.current_run_step += 1
                llm_docs_for_message_start = llm_docs_from_fetched_documents_cache(
                    ctx.fetched_documents_cache
                )
                retrieved_search_docs = saved_search_docs_from_llm_docs(
                    llm_docs_for_message_start
                )
                packets.append(
                    Packet(
                        ind=ctx.current_run_step,
                        obj=MessageStart(
                            content="", final_documents=retrieved_search_docs
                        ),
                    )
                )

            packets.append(Packet(ind=ctx.current_run_step, obj=obj))
        elif ev.data.type == "response.content_part.done":
            packets.append(Packet(ind=ctx.current_run_step, obj=SectionEnd()))
            ctx.current_output_index = None

    return packets
