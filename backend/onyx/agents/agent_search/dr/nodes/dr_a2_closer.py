import re
from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.constants import MAX_CHAT_HISTORY_MESSAGES
from onyx.agents.agent_search.dr.constants import MAX_NUM_CLOSER_SUGGESTIONS
from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.enums import ResearchAnswerPurpose
from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.agents.agent_search.dr.models import TestInfoCompleteResponse
from onyx.agents.agent_search.dr.states import FinalUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.dr.sub_agents.image_generation.models import (
    GeneratedImageFullResult,
)
from onyx.agents.agent_search.dr.utils import aggregate_context
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.agents.agent_search.dr.utils import get_chat_history_string
from onyx.agents.agent_search.dr.utils import get_prompt_question
from onyx.agents.agent_search.dr.utils import parse_plan_to_dict
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.chat.chat_utils import llm_doc_from_inference_section
from onyx.configs.agent_configs import TF_DR_TIMEOUT_LONG
from onyx.context.search.models import InferenceSection
from onyx.db.chat import create_search_doc_from_inference_section
from onyx.db.chat import update_db_session_with_messages
from onyx.db.models import ChatMessage__SearchDoc
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.db.models import SearchDoc as DbSearchDoc
from onyx.llm.utils import check_number_of_tokens
from onyx.prompts.chat_prompts import PROJECT_INSTRUCTIONS_SEPARATOR
from onyx.prompts.dr_prompts import FINAL_ANSWER_PROMPT_W_SUB_ANSWERS
from onyx.prompts.dr_prompts import FINAL_ANSWER_PROMPT_WITHOUT_SUB_ANSWERS
from onyx.prompts.dr_prompts import TEST_INFO_COMPLETE_PROMPT
from onyx.server.query_and_chat.streaming_models import CitationDelta
from onyx.server.query_and_chat.streaming_models import CitationStart
from onyx.server.query_and_chat.streaming_models import MessageStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.server.query_and_chat.streaming_models import StreamingType
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def extract_citation_numbers(text: str) -> list[int]:
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


def insert_chat_message_search_doc_pair(
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
    insert_chat_message_search_doc_pair(
        message_id, [search_doc.id for search_doc in search_docs], db_session
    )

    # lastly, insert the citations
    citation_dict: dict[int, int] = {}
    cited_doc_nrs = extract_citation_numbers(final_answer)
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


def closer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate | OrchestrationUpdate:
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

    research_type = graph_config.behavior.research_type

    assistant_system_prompt: str = state.assistant_system_prompt or ""
    assistant_task_prompt = state.assistant_task_prompt

    uploaded_context = state.uploaded_test_context or ""

    clarification = state.clarification
    prompt_question = get_prompt_question(base_question, clarification)

    chat_history_string = (
        get_chat_history_string(
            graph_config.inputs.prompt_builder.message_history,
            MAX_CHAT_HISTORY_MESSAGES,
        )
        or "(No chat history yet available)"
    )

    aggregated_context_w_docs = aggregate_context(
        state.iteration_responses, include_documents=True
    )

    aggregated_context_wo_docs = aggregate_context(
        state.iteration_responses, include_documents=False
    )

    iteration_responses_w_docs_string = aggregated_context_w_docs.context
    iteration_responses_wo_docs_string = aggregated_context_wo_docs.context
    all_cited_documents = aggregated_context_w_docs.cited_documents

    num_closer_suggestions = state.num_closer_suggestions

    if (
        num_closer_suggestions < MAX_NUM_CLOSER_SUGGESTIONS
        and research_type == ResearchType.DEEP
    ):
        test_info_complete_prompt = TEST_INFO_COMPLETE_PROMPT.build(
            base_question=prompt_question,
            questions_answers_claims=iteration_responses_wo_docs_string,
            chat_history_string=chat_history_string,
            high_level_plan=(
                state.plan_of_record.plan
                if state.plan_of_record
                else "No plan available"
            ),
        )

        test_info_complete_json = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=create_question_prompt(
                assistant_system_prompt,
                test_info_complete_prompt + (assistant_task_prompt or ""),
            ),
            schema=TestInfoCompleteResponse,
            timeout_override=TF_DR_TIMEOUT_LONG,
            # max_tokens=1000,
        )

        if test_info_complete_json.complete:
            pass

        else:
            return OrchestrationUpdate(
                tools_used=[DRPath.ORCHESTRATOR.value],
                query_list=[],
                log_messages=[
                    get_langgraph_node_log_string(
                        graph_component="main",
                        node_name="closer",
                        node_start_time=node_start_time,
                    )
                ],
                gaps=test_info_complete_json.gaps,
                num_closer_suggestions=num_closer_suggestions + 1,
            )

    retrieved_search_docs = convert_inference_sections_to_search_docs(
        all_cited_documents
    )

    write_custom_event(
        current_step_nr,
        MessageStart(
            content="",
            final_documents=retrieved_search_docs,
        ),
        writer,
    )

    if research_type in [ResearchType.THOUGHTFUL, ResearchType.FAST]:
        final_answer_base_prompt = FINAL_ANSWER_PROMPT_WITHOUT_SUB_ANSWERS
    elif research_type == ResearchType.DEEP:
        final_answer_base_prompt = FINAL_ANSWER_PROMPT_W_SUB_ANSWERS
    else:
        raise ValueError(f"Invalid research type: {research_type}")

    estimated_final_answer_prompt_tokens = check_number_of_tokens(
        final_answer_base_prompt.build(
            base_question=prompt_question,
            iteration_responses_string=iteration_responses_w_docs_string,
            chat_history_string=chat_history_string,
            uploaded_context=uploaded_context,
        )
    )

    # for DR, rely only on sub-answers and claims to save tokens if context is too long
    # TODO: consider compression step for Thoughtful mode if context is too long.
    # Should generally not be the case though.

    max_allowed_input_tokens = graph_config.tooling.primary_llm.config.max_input_tokens

    if (
        estimated_final_answer_prompt_tokens > 0.8 * max_allowed_input_tokens
        and research_type == ResearchType.DEEP
    ):
        iteration_responses_string = iteration_responses_wo_docs_string
    else:
        iteration_responses_string = iteration_responses_w_docs_string

    final_answer_prompt = final_answer_base_prompt.build(
        base_question=prompt_question,
        iteration_responses_string=iteration_responses_string,
        chat_history_string=chat_history_string,
        uploaded_context=uploaded_context,
    )

    if graph_config.inputs.project_instructions:
        assistant_system_prompt = (
            assistant_system_prompt
            + PROJECT_INSTRUCTIONS_SEPARATOR
            + (graph_config.inputs.project_instructions or "")
        )

    all_context_llmdocs = [
        llm_doc_from_inference_section(inference_section)
        for inference_section in all_cited_documents
    ]

    try:
        streamed_output, _, citation_infos = run_with_timeout(
            int(3 * TF_DR_TIMEOUT_LONG),
            lambda: stream_llm_answer(
                llm=graph_config.tooling.primary_llm,
                prompt=create_question_prompt(
                    assistant_system_prompt,
                    final_answer_prompt + (assistant_task_prompt or ""),
                ),
                event_name="basic_response",
                writer=writer,
                agent_answer_level=0,
                agent_answer_question_num=0,
                agent_answer_type="agent_level_answer",
                timeout_override=int(2 * TF_DR_TIMEOUT_LONG),
                answer_piece=StreamingType.MESSAGE_DELTA.value,
                ind=current_step_nr,
                context_docs=all_context_llmdocs,
                replace_citations=True,
                # max_tokens=None,
            ),
        )

        final_answer = "".join(streamed_output)
    except Exception as e:
        raise ValueError(f"Error in consolidate_research: {e}")

    write_custom_event(current_step_nr, SectionEnd(), writer)

    current_step_nr += 1

    write_custom_event(current_step_nr, CitationStart(), writer)
    write_custom_event(current_step_nr, CitationDelta(citations=citation_infos), writer)
    write_custom_event(current_step_nr, SectionEnd(), writer)

    current_step_nr += 1

    # Log the research agent steps
    # save_iteration(
    #     state,
    #     graph_config,
    #     aggregated_context,
    #     final_answer,
    #     all_cited_documents,
    #     is_internet_marker_dict,
    # )

    return FinalUpdate(
        final_answer=final_answer,
        all_cited_documents=all_cited_documents,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="closer",
                node_start_time=node_start_time,
            )
        ],
    )
