import re
from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.sub_agents.image_generation.models import (
    GeneratedImageFullResult,
)
from onyx.agents.agent_search.dr.utils import aggregate_context
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.agents.agent_search.dr.utils import parse_plan_to_dict
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.context.search.models import InferenceSection
from onyx.db.chat import create_search_doc_from_inference_section
from onyx.db.chat import update_db_session_with_messages
from onyx.db.models import ChatMessage__SearchDoc
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.db.models import SearchDoc as DbSearchDoc
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.utils.logger import setup_logger

logger = setup_logger()


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


def replace_citation_with_link(match: re.Match[str], docs: list[DbSearchDoc]) -> str:
    citation_content = match.group(1)  # e.g., "3" or "3, 5, 7"
    numbers = [int(num.strip()) for num in citation_content.split(",")]

    # For multiple citations like [[3, 5, 7]], create separate linked citations
    linked_citations = []
    for num in numbers:
        if num - 1 < len(docs):  # Check bounds
            link = docs[num - 1].link or ""
            linked_citations.append(f"[[{num}]]({link})")
        else:
            linked_citations.append(f"[[{num}]]")  # No link if out of bounds

    return "".join(linked_citations)


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


def save_iteration(
    state: MainState,
    graph_config: GraphConfig,
    aggregated_context: AggregatedDRContext,
    final_answer: str,
    all_cited_documents: list[InferenceSection],
    is_internet_marker_dict: dict[str, bool],
    num_tokens: int,
) -> None:
    db_session = graph_config.persistence.db_session
    message_id = graph_config.persistence.message_id
    research_type = graph_config.behavior.research_type
    db_session = graph_config.persistence.db_session

    # first, insert the search_docs
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

    # TODO: generate plan as dict in the first place
    plan_of_record = state.plan_of_record.plan if state.plan_of_record else ""
    plan_of_record_dict = parse_plan_to_dict(plan_of_record)

    # Update the chat message and its parent message in database
    update_db_session_with_messages(
        db_session=db_session,
        chat_message_id=message_id,
        chat_session_id=graph_config.persistence.chat_session_id,
        is_agentic=graph_config.behavior.use_agentic_search,
        message=final_answer,
        citations=citation_dict,
        research_type=research_type,
        research_plan=plan_of_record_dict,
        final_documents=search_docs,
        update_parent_message=True,
        research_answer_purpose=ResearchAnswerPurpose.ANSWER,
        token_count=num_tokens,
    )

    for iteration_preparation in state.iteration_instructions:
        research_agent_iteration_step = ResearchAgentIteration(
            primary_question_id=message_id,
            reasoning=iteration_preparation.reasoning,
            purpose=iteration_preparation.purpose,
            iteration_nr=iteration_preparation.iteration_nr,
        )
        db_session.add(research_agent_iteration_step)

    for iteration_answer in aggregated_context.global_iteration_responses:

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
            queries=iteration_answer.queries,
        )
        db_session.add(research_agent_iteration_sub_step)

    db_session.commit()


def logging(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> LoggerUpdate:
    """
    LangGraph node to close the DR process and finalize the answer.
    """

    node_start_time = datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    current_step_nr = state.current_step_nr

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = state.original_question
    if not base_question:
        raise ValueError("Question is required for closer")

    aggregated_context = aggregate_context(
        state.iteration_responses, include_documents=True
    )

    all_cited_documents = aggregated_context.cited_documents

    is_internet_marker_dict = aggregated_context.is_internet_marker_dict

    final_answer = state.final_answer or ""
    llm_provider = graph_config.tooling.primary_llm.config.model_provider
    llm_model_name = graph_config.tooling.primary_llm.config.model_name

    llm_tokenizer = get_tokenizer(
        model_name=llm_model_name,
        provider_type=llm_provider,
    )
    num_tokens = len(llm_tokenizer.encode(final_answer or ""))

    write_custom_event(current_step_nr, OverallStop(), writer)

    # Log the research agent steps
    save_iteration(
        state,
        graph_config,
        aggregated_context,
        final_answer,
        all_cited_documents,
        is_internet_marker_dict,
        num_tokens,
    )

    return LoggerUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="logger",
                node_start_time=node_start_time,
            )
        ],
    )
