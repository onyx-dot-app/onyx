import re
from typing import cast
from uuid import UUID

from agents import Agent
from agents import ModelSettings
from agents import RunItemStreamEvent
from agents.extensions.models.litellm_model import LitellmModel
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.sub_agents.image_generation.models import (
    GeneratedImageFullResult,
)
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.chat.turn.infra.chat_turn_event_stream import OnyxRunner
from onyx.chat.turn.infra.chat_turn_orchestration import unified_event_stream
from onyx.chat.turn.infra.packet_translation import default_packet_translation
from onyx.chat.turn.models import MyContext
from onyx.chat.turn.models import RunDependencies
from onyx.context.search.models import InferenceSection
from onyx.db.chat import create_search_doc_from_inference_section
from onyx.db.chat import update_db_session_with_messages
from onyx.db.models import ChatMessage__SearchDoc
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.tool_implementations_v2.internal_search import internal_search
from onyx.tools.tool_implementations_v2.web import web_fetch
from onyx.tools.tool_implementations_v2.web import web_search


# TODO: Dependency injection?
@unified_event_stream
def fast_chat_turn(messages: list[dict], dependencies: RunDependencies) -> None:
    ctx = MyContext(
        run_dependencies=dependencies,
        aggregated_context=AggregatedDRContext(
            context="context",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],  # TODO: the only field that matters for now
        ),
        iteration_instructions=[],
    )
    agent = Agent(
        name="Assistant",
        model=LitellmModel(
            model=dependencies.llm.config.model_name,
            api_key=dependencies.llm.config.api_key,
        ),
        tools=[web_search, web_fetch, internal_search],
        model_settings=ModelSettings(
            temperature=0.0,
            include_usage=True,
        ),
    )

    bridge = OnyxRunner().run_streamed(agent, messages, context=ctx, max_turns=100)
    final_answer = "filler final answer"
    for ev in bridge.events():
        ctx.current_run_step
        obj = default_packet_translation(ev)
        print(ev)
        # TODO this obviously won't work for cancellation
        if isinstance(ev, RunItemStreamEvent):
            ev = cast(RunItemStreamEvent, ev)
            if ev.name == "message_output_created":
                final_answer = ev.item.raw_item.content[0].text
        if obj:
            dependencies.emitter.emit(Packet(ind=ctx.current_run_step, obj=obj))
    save_iteration(
        db_session=dependencies.db_session,
        message_id=dependencies.dependencies_to_maybe_remove.message_id,
        chat_session_id=dependencies.dependencies_to_maybe_remove.chat_session_id,
        research_type=dependencies.dependencies_to_maybe_remove.research_type,
        ctx=ctx,
        final_answer=final_answer,
        all_cited_documents=[],
    )
    # TODO: Error handling
    # Should there be a timeout and some error on the queue?
    dependencies.emitter.emit(
        Packet(ind=ctx.current_run_step, obj=OverallStop(type="stop"))
    )


# TODO: Figure out a way to persist information is robust to cancellation,
# modular so easily testable in unit tests and evals [likely injecting some higher
# level session manager and span sink], potentially has some robustness off the critical path,
# and promotes clean separation of concerns.
def save_iteration(
    db_session: Session,
    message_id: int,
    chat_session_id: UUID,
    research_type: ResearchType,
    ctx: MyContext,
    final_answer: str,
    all_cited_documents: list[InferenceSection],
) -> None:
    # first, insert the search_docs
    is_internet_marker_dict = {}
    search_docs = [
        create_search_doc_from_inference_section(
            inference_section=inference_section,
            is_internet=is_internet_marker_dict.get(
                inference_section.center_chunk.document_id, False
            ),  # TODO: revisit
            db_session=db_session,
            commit=False,
        )
        for inference_section in all_cited_documents
    ]

    # then, map_search_docs to message
    _insert_chat_message_search_doc_pair(
        message_id, [search_doc.id for search_doc in search_docs], db_session
    )

    # lastly, insert the citations
    citation_dict: dict[int, int] = {}
    cited_doc_nrs = _extract_citation_numbers(final_answer)
    if search_docs:
        for cited_doc_nr in cited_doc_nrs:
            citation_dict[cited_doc_nr] = search_docs[cited_doc_nr - 1].id

    # Update the chat message and its parent message in database
    update_db_session_with_messages(
        db_session=db_session,
        chat_message_id=message_id,
        chat_session_id=chat_session_id,
        is_agentic=research_type == ResearchType.DEEP,
        message=final_answer,
        citations=citation_dict,
        research_type=research_type,
        research_plan={},
        final_documents=search_docs,
        update_parent_message=True,
        research_answer_purpose=ResearchAnswerPurpose.ANSWER,
        token_count=0,
    )

    for iteration_preparation in ctx.iteration_instructions:
        research_agent_iteration_step = ResearchAgentIteration(
            primary_question_id=message_id,
            reasoning=iteration_preparation.reasoning,
            purpose=iteration_preparation.purpose,
            iteration_nr=iteration_preparation.iteration_nr,
        )
        db_session.add(research_agent_iteration_step)

    for iteration_answer in ctx.aggregated_context.global_iteration_responses:

        retrieved_search_docs = convert_inference_sections_to_search_docs(
            list(iteration_answer.cited_documents.values())
        )

        # Convert SavedSearchDoc objects to JSON-serializable format
        serialized_search_docs = [doc.model_dump() for doc in retrieved_search_docs]

        research_agent_iteration_sub_step = ResearchAgentIterationSubStep(
            primary_question_id=message_id,
            iteration_nr=iteration_answer.iteration_nr,
            iteration_sub_step_nr=iteration_answer.parallelization_nr,
            sub_step_instructions=iteration_answer.question,
            sub_step_tool_id=iteration_answer.tool_id,
            sub_answer=iteration_answer.answer,
            reasoning=iteration_answer.reasoning,
            claims=iteration_answer.claims,
            cited_doc_results=serialized_search_docs,
            generated_images=(
                GeneratedImageFullResult(images=iteration_answer.generated_images)
                if iteration_answer.generated_images
                else None
            ),
            additional_data=iteration_answer.additional_data,
        )
        db_session.add(research_agent_iteration_sub_step)

    db_session.commit()


def _insert_chat_message_search_doc_pair(
    message_id: int, search_doc_ids: list[int], db_session: Session
) -> None:
    """
    Insert a pair of message_id and search_doc_id into the chat_message__search_doc table.

    Args:
        message_id: The ID of the chat message
        search_doc_id: The ID of the search document
        db_session: The database session
    """
    for search_doc_id in search_doc_ids:
        chat_message_search_doc = ChatMessage__SearchDoc(
            chat_message_id=message_id, search_doc_id=search_doc_id
        )
        db_session.add(chat_message_search_doc)


def _extract_citation_numbers(text: str) -> list[int]:
    """
    Extract all citation numbers from text in the format [[<number>]] or [[<number_1>, <number_2>, ...]].
    Returns a list of all unique citation numbers found.
    """
    # Pattern to match [[number]] or [[number1, number2, ...]]
    pattern = r"\[\[(\d+(?:,\s*\d+)*)\]\]"
    matches = re.findall(pattern, text)

    cited_numbers = []
    for match in matches:
        # Split by comma and extract all numbers
        numbers = [int(num.strip()) for num in match.split(",")]
        cited_numbers.extend(numbers)

    return list(set(cited_numbers))  # Return unique numbers
