from collections.abc import Iterator
from collections.abc import Sequence
from uuid import UUID

from agents.tracing import trace

from onyx.agents.agent_framework.models import RunItemStreamEvent
from onyx.agents.agent_framework.models import StreamEvent
from onyx.agents.agent_framework.models import ToolCallStreamItem
from onyx.agents.agent_framework.query import query
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.chat.chat_utils import llm_docs_from_fetched_documents_cache
from onyx.chat.chat_utils import saved_search_docs_from_llm_docs
from onyx.chat.memories import get_memories
from onyx.chat.models import PromptConfig
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
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.chat.turn.prompts.custom_instruction import build_custom_instructions
from onyx.chat.turn.save_turn import extract_final_answer_from_packets
from onyx.chat.turn.save_turn import save_turn
from onyx.llm.message_types import ChatCompletionMessage
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.adapter_v1_to_v2 import force_use_tool_to_function_tool_names
from onyx.tools.force import ForceUseTool
from onyx.tools.tool import Tool

MAX_ITERATIONS = 10


# TODO -- this can be refactored out and played with in evals + normal demo
def _run_agent_loop(
    messages: list[ChatCompletionMessage],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    ctx: ChatTurnContext,
    prompt_config: PromptConfig,
    force_use_tool: ForceUseTool | None = None,
) -> None:
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
        # TODO: The system is rather prompt-cache efficient except for rebuilding the system prompt.
        # The biggest offender is when we hit max iterations and then all the tool calls cannot
        # be cached anymore since the system message will be differ in that it will have no tools.
        if not is_connected(chat_session_id, dependencies.redis_client):
            _emit_clean_up_packets(dependencies, ctx)
            break
        langchain_system_message = default_build_system_message_v2(
            dependencies.prompt_config,
            dependencies.llm.config,
            memories,
            available_tools,
            ctx.should_cite_documents,
        )
        new_system_prompt: ChatCompletionMessage = {
            "role": "system",
            "content": str(langchain_system_message.content),
        }
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
        query_result = query(
            llm_with_default_settings=dependencies.llm,
            messages=current_messages,
            tools=available_tools,
            context=ctx,
            tool_choice=tool_choice,
        )
        tool_call_events = _process_query_stream(
            query_result.stream, chat_session_id, dependencies, ctx
        )

        agent_turn_messages = [
            msg
            for msg in query_result.new_messages_stateful
            if msg.get("role") != "user"
        ]

        # Apply context handlers in order:
        # 1. Add task prompt reminder
        last_iteration_included_web_search = any(
            tool_call.name == "web_search" for tool_call in tool_call_events
        )
        agent_turn_messages = maybe_append_reminder(
            agent_turn_messages,
            prompt_config,
            ctx.should_cite_documents,
            last_iteration_included_web_search,
        )

        # 2. Assign citation numbers to tool call outputs
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


def _process_query_stream(
    stream: Iterator[StreamEvent],
    chat_session_id: UUID,
    dependencies: ChatTurnDependencies,
    ctx: ChatTurnContext,
) -> list[ToolCallStreamItem]:
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
    tool_call_events: list[ToolCallStreamItem] = []
    message_section_open = False
    reasoning_section_open = False

    for event in stream:
        connected = is_connected(
            chat_session_id,
            dependencies.redis_client,
        )
        if not connected:
            _emit_clean_up_packets(dependencies, ctx)
            break

        if isinstance(event, RunItemStreamEvent):
            if event.type == "message_start" and not message_section_open:
                _start_message_section(dependencies, ctx)
                message_section_open = True
            elif event.type == "message_done" and message_section_open:
                _end_section(dependencies, ctx)
                message_section_open = False
            elif event.type == "reasoning_start" and not reasoning_section_open:
                _start_reasoning_section(dependencies, ctx)
                reasoning_section_open = True
            elif event.type == "reasoning_done" and reasoning_section_open:
                _end_section(dependencies, ctx)
                reasoning_section_open = False
            elif event.type == "tool_call" and isinstance(
                event.details, ToolCallStreamItem
            ):
                tool_call_events.append(event.details)
            continue

        delta = event.choice.delta
        if delta.reasoning_content:
            if not reasoning_section_open:
                _start_reasoning_section(dependencies, ctx)
                reasoning_section_open = True
            dependencies.emitter.emit(
                Packet(
                    ind=ctx.current_run_step,
                    obj=ReasoningDelta(reasoning=delta.reasoning_content),
                )
            )

        if delta.content:
            if not message_section_open:
                _start_message_section(dependencies, ctx)
                message_section_open = True

            if processor:
                final_answer_piece = ""
                for response_part in processor.process_token(delta.content):
                    if isinstance(response_part, CitationInfo):
                        ctx.citations.append(response_part)
                    else:
                        final_answer_piece += response_part.answer_piece or ""
            else:
                final_answer_piece = delta.content

            if final_answer_piece:
                dependencies.emitter.emit(
                    Packet(
                        ind=ctx.current_run_step,
                        obj=MessageDelta(content=final_answer_piece),
                    )
                )

    return tool_call_events


# TODO: Maybe in general there's a cleaner way to handle cancellation in the middle of a tool call?
def _emit_clean_up_packets(
    dependencies: ChatTurnDependencies, ctx: ChatTurnContext
) -> None:
    has_active_message = (
        dependencies.emitter.packet_history
        and dependencies.emitter.packet_history[-1].obj.type == "message_delta"
    )
    if has_active_message:
        _end_section(dependencies, ctx)
    _start_message_section(dependencies, ctx, content_override="Cancelled")
    _end_section(dependencies, ctx)


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


def _start_message_section(
    dependencies: ChatTurnDependencies,
    ctx: ChatTurnContext,
    content_override: str = "",
) -> None:
    ctx.current_run_step += 1
    llm_docs_for_message_start = llm_docs_from_fetched_documents_cache(
        ctx.fetched_documents_cache
    )
    retrieved_search_docs = saved_search_docs_from_llm_docs(llm_docs_for_message_start)
    final_documents = None if content_override else retrieved_search_docs
    dependencies.emitter.emit(
        Packet(
            ind=ctx.current_run_step,
            obj=MessageStart(content=content_override, final_documents=final_documents),
        )
    )


def _start_reasoning_section(
    dependencies: ChatTurnDependencies,
    ctx: ChatTurnContext,
) -> None:
    ctx.current_run_step += 1
    dependencies.emitter.emit(Packet(ind=ctx.current_run_step, obj=ReasoningStart()))


def _end_section(dependencies: ChatTurnDependencies, ctx: ChatTurnContext) -> None:
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=SectionEnd(type="section_end"))
    )
