# TODO: Figure out a way to persist information is robust to cancellation,
# modular so easily testable in unit tests and evals [likely injecting some higher
# level session manager and span sink], potentially has some robustness off the critical path,
# and promotes clean separation of concerns.
import re
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.sub_agents.image_generation.models import (
    GeneratedImageFullResult,
)
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.chat.turn.models import ChatTurnContext
from onyx.context.search.models import InferenceSection
from onyx.db.chat import create_search_doc_from_inference_section
from onyx.db.chat import update_db_session_with_messages
from onyx.db.models import ChatMessage__SearchDoc
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.streaming_models import MessageDelta
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import Packet


def save_iteration(
    db_session: Session,
    message_id: int,
    chat_session_id: UUID,
    research_type: ResearchType,
    ctx: ChatTurnContext,
    final_answer: str,
    all_cited_documents: list[InferenceSection],
) -> None:
    # first, insert the search_docs
    is_internet_marker_dict: dict[str, bool] = {}
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
    llm_tokenizer = get_tokenizer(
        model_name=ctx.run_dependencies.llm.config.model_name,
        provider_type=ctx.run_dependencies.llm.config.model_provider,
    )
    num_tokens = len(llm_tokenizer.encode(final_answer or ""))
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
        token_count=num_tokens,
    )

    # TODO: I don't think this is the ideal schema for all use cases
    # find a better schema to store tool and reasoning calls
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
            is_web_fetch=iteration_answer.is_web_fetch,
            queries=iteration_answer.queries,
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


def extract_final_answer_from_packets(packet_history: list[Packet]) -> str:
    """Extract the final answer by concatenating all MessageDelta content."""
    final_answer = ""
    for packet in packet_history:
        if isinstance(packet.obj, MessageDelta) or isinstance(packet.obj, MessageStart):
            final_answer += packet.obj.content
    return final_answer
