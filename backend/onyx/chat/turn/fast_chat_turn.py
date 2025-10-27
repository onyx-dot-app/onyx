from dataclasses import replace
from typing import cast
from typing import TYPE_CHECKING
from uuid import UUID

from agents import Agent
from agents import RawResponsesStreamEvent
from agents import RunResultStreaming
from agents import ToolCallItem
from agents.tracing import trace

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.agents.agent_sdk.message_types import UserMessage
from onyx.agents.agent_sdk.monkey_patches import (
    monkey_patch_convert_tool_choice_to_ignore_openai_hosted_web_search,
)
from onyx.agents.agent_sdk.sync_agent_stream_adapter import SyncAgentStream
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.chat.chat_utils import saved_search_docs_from_llm_docs
from onyx.chat.models import PromptConfig
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.stop_signal_checker import reset_cancel_status
from onyx.chat.stream_processing.citation_processing import CitationProcessor
from onyx.chat.stream_processing.utils import map_document_id_order_v2
from onyx.chat.turn.context_handler.citation import (
    assign_citation_numbers_recent_tool_calls,
)
from onyx.chat.turn.context_handler.task_prompt import update_task_prompt
from onyx.chat.turn.infra.chat_turn_event_stream import unified_event_stream
from onyx.chat.turn.infra.session_sink import extract_final_answer_from_packets
from onyx.chat.turn.infra.session_sink import save_iteration
from onyx.chat.turn.models import AgentToolType
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketObj
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.adapter_v1_to_v2 import force_use_tool_to_function_tool_names
from onyx.tools.adapter_v1_to_v2 import tools_to_function_tools
from onyx.tools.force import ForceUseTool

if TYPE_CHECKING:
    from litellm import ResponseFunctionToolCall


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
    # Split messages into three parts for clear tracking
    # TODO: Think about terminal tool calls like image gen
    # in multi turn conversations
    chat_history = messages[:-1]
    current_user_message = messages[-1]
    if (
        not isinstance(current_user_message, dict)
        or current_user_message.get("role") != "user"
    ):
        raise ValueError("Last message must be a user message")
    current_user_message_typed: UserMessage = current_user_message  # type: ignore
    agent_turn_messages: list[AgentSDKMessage] = []
    last_call_is_final = False
    first_iteration = True

    while not last_call_is_final:
        current_messages = chat_history + [current_user_message] + agent_turn_messages
        tool_choice = (
            force_use_tool_to_function_tool_names(force_use_tool, dependencies.tools)
            if first_iteration and force_use_tool
            else None
        ) or "auto"
        model_settings = replace(dependencies.model_settings, tool_choice=tool_choice)
        agent = Agent(
            name="Assistant",
            model=dependencies.llm_model,
            tools=cast(
                list[AgentToolType], tools_to_function_tools(dependencies.tools)
            ),
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
        # The new messages are everything after chat_history + current_user_message
        previous_message_count = len(chat_history) + 1
        agent_turn_messages = [
            cast(AgentSDKMessage, msg)
            for msg in all_messages_after_stream[previous_message_count:]
        ]

        agent_turn_messages = list(
            update_task_prompt(
                current_user_message_typed,
                agent_turn_messages,
                prompt_config,
                ctx.should_cite_documents,
            )
        )
        citation_result = assign_citation_numbers_recent_tool_calls(
            agent_turn_messages, ctx
        )
        agent_turn_messages = list(citation_result.updated_messages)
        ctx.ordered_fetched_documents.extend(citation_result.new_llm_docs)
        ctx.documents_cited_count += citation_result.num_docs_cited
        ctx.tool_calls_cited_count += citation_result.num_tool_calls_cited

        # TODO: Make this configurable on OnyxAgent level
        stopping_tools = ["image_generation"]
        if len(tool_call_events) == 0 or any(
            tool.name in stopping_tools for tool in tool_call_events
        ):
            last_call_is_final = True
        first_iteration = False


def _fast_chat_turn_core(
    messages: list[AgentSDKMessage],
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
        messages: List of chat messages
        dependencies: Chat turn dependencies
        chat_session_id: Chat session ID
        message_id: Message ID
        research_type: Research type
        global_iteration_responses: Optional list of iteration answers to inject for testing
        cited_documents: Optional list of cited documents to inject for testing
    """
    reset_cancel_status(
        chat_session_id,
        dependencies.redis_client,
    )
    ctx = starter_context or ChatTurnContext(
        run_dependencies=dependencies,
        aggregated_context=AggregatedDRContext(
            context="context",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        iteration_instructions=[],
        chat_session_id=chat_session_id,
        message_id=message_id,
        research_type=research_type,
    )
    with trace("fast_chat_turn"):
        _run_agent_loop(
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
    save_iteration(
        db_session=dependencies.db_session,
        message_id=message_id,
        chat_session_id=chat_session_id,
        research_type=research_type,
        ctx=ctx,
        final_answer=final_answer,
        unordered_fetched_inference_sections=ctx.unordered_fetched_inference_sections,
        ordered_fetched_documents=ctx.ordered_fetched_documents,
    )
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=OverallStop(type="stop"))
    )


@unified_event_stream
def fast_chat_turn(
    messages: list[AgentSDKMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
) -> None:
    """Main fast chat turn function that calls the core logic with default parameters."""
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

    mapping = map_document_id_order_v2(ctx.ordered_fetched_documents)
    if ctx.ordered_fetched_documents:
        processor = CitationProcessor(
            context_docs=ctx.ordered_fetched_documents,
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
        obj = _default_packet_translation(ev, ctx, processor)
        if obj:
            dependencies.emitter.emit(Packet(ind=ctx.current_run_step, obj=obj))
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
    if ctx.collected_citations:
        dependencies.emitter.emit(Packet(ind=index, obj=CitationStart()))
        dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=CitationDelta(citations=ctx.collected_citations),  # type: ignore[arg-type]
            )
        )
        dependencies.emitter.emit(Packet(ind=index, obj=SectionEnd(type="section_end")))
    ctx.current_run_step = index


def _default_packet_translation(
    ev: object, ctx: ChatTurnContext, processor: CitationProcessor | None
) -> PacketObj | None:
    if isinstance(ev, RawResponsesStreamEvent):
        obj: PacketObj | None = None
        if ev.data.type == "response.content_part.added":
            retrieved_search_docs = saved_search_docs_from_llm_docs(
                ctx.ordered_fetched_documents
            )
            obj = MessageStart(
                type="message_start", content="", final_documents=retrieved_search_docs
            )
        elif ev.data.type == "response.output_text.delta" and len(ev.data.delta) > 0:
            if processor:
                final_answer_piece = ""
                for response_part in processor.process_token(ev.data.delta):
                    if isinstance(response_part, CitationInfo):
                        ctx.collected_citations.append(response_part)
                    else:
                        final_answer_piece += response_part.answer_piece or ""
                obj = MessageDelta(type="message_delta", content=final_answer_piece)
            else:
                obj = MessageDelta(type="message_delta", content=ev.data.delta)
        elif ev.data.type == "response.content_part.done":
            obj = SectionEnd(type="section_end")
        return obj
    return None
