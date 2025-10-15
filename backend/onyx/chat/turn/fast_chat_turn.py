from typing import cast
from uuid import UUID

from agents import Agent
from agents import ModelSettings
from agents import RawResponsesStreamEvent
from agents import StopAtTools

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.chat.chat_utils import llm_doc_from_inference_section
from onyx.chat.stop_signal_checker import is_connected
from onyx.chat.stop_signal_checker import reset_cancel_status
from onyx.chat.stream_processing.citation_processing import CitationProcessor
from onyx.chat.turn.infra.chat_turn_event_stream import unified_event_stream
from onyx.chat.turn.infra.session_sink import extract_final_answer_from_packets
from onyx.chat.turn.infra.session_sink import save_iteration
from onyx.chat.turn.infra.sync_agent_stream_adapter import SyncAgentStream
from onyx.chat.turn.models import AgentToolType
from onyx.chat.turn.models import ChatTurnContext
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.context.search.models import InferenceSection
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import PacketObj
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations_v2.image_generation import image_generation_tool


def _fast_chat_turn_core(
    messages: list[dict],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
    # Dependency injectable arguments for testing
    starter_global_iteration_responses: list[IterationAnswer] | None = None,
    starter_cited_documents: list[InferenceSection] | None = None,
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
    ctx = ChatTurnContext(
        run_dependencies=dependencies,
        aggregated_context=AggregatedDRContext(
            context="context",
            cited_documents=starter_cited_documents or [],
            is_internet_marker_dict={},
            global_iteration_responses=starter_global_iteration_responses or [],
        ),
        iteration_instructions=[],
        chat_session_id=chat_session_id,
        message_id=message_id,
        research_type=research_type,
    )
    agent = Agent(
        name="Assistant",
        model=dependencies.llm_model,
        tools=cast(list[AgentToolType], dependencies.tools),
        model_settings=ModelSettings(
            temperature=dependencies.llm.config.temperature,
            include_usage=True,
        ),
        tool_use_behavior=StopAtTools(stop_at_tool_names=[image_generation_tool.name]),
    )
    # By default, the agent can only take 10 turns. For our use case, it should be higher.
    max_turns = 25
    agent_stream: SyncAgentStream = SyncAgentStream(
        agent=agent,
        input=messages,
        context=ctx,
        max_turns=max_turns,
    )
    for ev in agent_stream:
        connected = is_connected(
            chat_session_id,
            dependencies.redis_client,
        )
        if not connected:
            _emit_clean_up_packets(dependencies, ctx)
            agent_stream.cancel()
            break
        obj = _default_packet_translation(ev, ctx)
        if obj:
            dependencies.emitter.emit(Packet(ind=ctx.current_run_step, obj=obj))
    final_answer = extract_final_answer_from_packets(
        dependencies.emitter.packet_history
    )

    all_cited_documents = []
    if ctx.aggregated_context.global_iteration_responses:
        context_docs = _gather_context_docs_from_iteration_answers(
            ctx.aggregated_context.global_iteration_responses
        )
        all_cited_documents = context_docs
        if context_docs and final_answer:
            _process_citations_for_final_answer(
                final_answer=final_answer,
                context_docs=context_docs,
                dependencies=dependencies,
                ctx=ctx,
            )

    save_iteration(
        db_session=dependencies.db_session,
        message_id=message_id,
        chat_session_id=chat_session_id,
        research_type=research_type,
        ctx=ctx,
        final_answer=final_answer,
        all_cited_documents=all_cited_documents,
    )
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=OverallStop(type="stop"))
    )


@unified_event_stream
def fast_chat_turn(
    messages: list[dict],
    dependencies: ChatTurnDependencies,
    chat_session_id: UUID,
    message_id: int,
    research_type: ResearchType,
) -> None:
    """Main fast chat turn function that calls the core logic with default parameters."""
    _fast_chat_turn_core(
        messages,
        dependencies,
        chat_session_id,
        message_id,
        research_type,
        starter_global_iteration_responses=None,
    )


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


def _gather_context_docs_from_iteration_answers(
    iteration_answers: list[IterationAnswer],
) -> list[InferenceSection]:
    """Gather cited documents from iteration answers for citation processing."""
    context_docs: list[InferenceSection] = []

    for iteration_answer in iteration_answers:
        # Extract cited documents from this iteration
        for inference_section in iteration_answer.cited_documents.values():
            # Avoid duplicates by checking document_id
            if not any(
                doc.center_chunk.document_id
                == inference_section.center_chunk.document_id
                for doc in context_docs
            ):
                context_docs.append(inference_section)

    return context_docs


def _process_citations_for_final_answer(
    final_answer: str,
    context_docs: list[InferenceSection],
    dependencies: ChatTurnDependencies,
    ctx: ChatTurnContext,
) -> None:
    index = ctx.current_run_step + 1
    """Process citations in the final answer and emit citation events."""
    from onyx.chat.stream_processing.utils import DocumentIdOrderMapping

    # Convert InferenceSection objects to LlmDoc objects for citation processing
    llm_docs = [llm_doc_from_inference_section(section) for section in context_docs]

    # Create document ID to rank mappings (simple 1-based indexing)
    final_doc_id_to_rank_map = DocumentIdOrderMapping(
        order_mapping={doc.document_id: i + 1 for i, doc in enumerate(llm_docs)}
    )
    display_doc_id_to_rank_map = final_doc_id_to_rank_map  # Same mapping for display

    # Initialize citation processor
    citation_processor = CitationProcessor(
        context_docs=llm_docs,
        final_doc_id_to_rank_map=final_doc_id_to_rank_map,
        display_doc_id_to_rank_map=display_doc_id_to_rank_map,
    )

    # Process the final answer through citation processor
    collected_citations: list = []
    for response_part in citation_processor.process_token(final_answer):
        if hasattr(response_part, "citation_num"):  # It's a CitationInfo
            collected_citations.append(response_part)

    # Emit citation events if we found any citations
    if collected_citations:
        dependencies.emitter.emit(Packet(ind=index, obj=CitationStart()))
        dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=CitationDelta(citations=collected_citations),  # type: ignore[arg-type]
            )
        )
        dependencies.emitter.emit(Packet(ind=index, obj=SectionEnd(type="section_end")))
    ctx.current_run_step = index


def _default_packet_translation(ev: object, ctx: ChatTurnContext) -> PacketObj | None:
    if isinstance(ev, RawResponsesStreamEvent):
        # TODO: might need some variation here for different types of models
        # OpenAI packet translator
        obj: PacketObj | None = None
        if ev.data.type == "response.content_part.added":
            retrieved_search_docs = convert_inference_sections_to_search_docs(
                ctx.aggregated_context.cited_documents
            )
            obj = MessageStart(
                type="message_start", content="", final_documents=retrieved_search_docs
            )
        elif ev.data.type == "response.output_text.delta":
            obj = MessageDelta(type="message_delta", content=ev.data.delta)
        elif ev.data.type == "response.content_part.done":
            obj = SectionEnd(type="section_end")
        return obj
    return None
