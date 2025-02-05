from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.main.models import (
    AgentRefinedMetrics,
)
from onyx.agents.agent_search.deep_search.main.operations import get_query_info
from onyx.agents.agent_search.deep_search.main.operations import logger
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.deep_search.main.states import (
    RefinedAnswerUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    get_prompt_enrichment_components,
)
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.models import InferenceSection
from onyx.agents.agent_search.shared_graph_utils.models import RefinedAgentStats
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    dispatch_main_answer_stop_info,
)
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.agents.agent_search.shared_graph_utils.utils import relevance_from_docs
from onyx.agents.agent_search.shared_graph_utils.utils import (
    remove_document_citations,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import ExtendedToolResponse
from onyx.configs.agent_configs import AGENT_MAX_ANSWER_CONTEXT_DOCS
from onyx.configs.agent_configs import AGENT_MIN_ORIG_QUESTION_DOCS
from onyx.prompts.agent_search import (
    REFINED_ANSWER_PROMPT_W_SUB_QUESTIONS,
)
from onyx.prompts.agent_search import (
    REFINED_ANSWER_PROMPT_WO_SUB_QUESTIONS,
)
from onyx.prompts.agent_search import (
    SUB_QUESTION_ANSWER_TEMPLATE_REFINED,
)
from onyx.prompts.agent_search import UNKNOWN_ANSWER
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses


def generate_refined_answer(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> RefinedAnswerUpdate:
    """
    LangGraph node to generate the refined answer.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    prompt_enrichment_components = get_prompt_enrichment_components(graph_config)

    persona_contextualized_prompt = (
        prompt_enrichment_components.persona_prompts.contextualized_prompt
    )

    verified_reranked_documents = state.verified_reranked_documents
    sub_questions_cited_documents = state.cited_documents
    original_question_verified_documents = (
        state.orig_question_verified_reranked_documents
    )
    original_question_retrieved_documents = state.orig_question_retrieved_documents

    consolidated_context_docs: list[InferenceSection] = sub_questions_cited_documents

    counter = 0
    for original_doc_number, original_doc in enumerate(
        original_question_verified_documents
    ):
        if original_doc_number not in sub_questions_cited_documents:
            if (
                counter <= AGENT_MIN_ORIG_QUESTION_DOCS
                or len(consolidated_context_docs)
                < 1.5
                * AGENT_MAX_ANSWER_CONTEXT_DOCS  # allow for larger context in refinement
            ):
                consolidated_context_docs.append(original_doc)
                counter += 1

    # sort docs by their scores - though the scores refer to different questions
    relevant_docs = dedup_inference_sections(
        consolidated_context_docs, consolidated_context_docs
    )

    streaming_docs = (
        relevant_docs
        if len(relevant_docs) > 0
        else original_question_retrieved_documents[:15]
    )

    query_info = get_query_info(state.orig_question_sub_query_retrieval_results)
    assert (
        graph_config.tooling.search_tool
    ), "search_tool must be provided for agentic search"
    # stream refined answer docs, or original question docs if no relevant docs are found
    relevance_list = relevance_from_docs(relevant_docs)
    for tool_response in yield_search_responses(
        query=question,
        reranked_sections=streaming_docs,
        final_context_sections=streaming_docs,
        search_query_info=query_info,
        get_section_relevance=lambda: relevance_list,
        search_tool=graph_config.tooling.search_tool,
    ):
        write_custom_event(
            "tool_response",
            ExtendedToolResponse(
                id=tool_response.id,
                response=tool_response.response,
                level=1,
                level_question_num=0,  # 0, 0 is the base question
            ),
            writer,
        )

    if len(verified_reranked_documents) > 0:
        refined_doc_effectiveness = len(relevant_docs) / len(
            verified_reranked_documents
        )
    else:
        refined_doc_effectiveness = 10.0

    sub_question_answer_results = state.sub_question_results

    answered_sub_question_answer_list: list[str] = []
    sub_questions: list[str] = []
    initial_answered_sub_questions: set[str] = set()
    refined_answered_sub_questions: set[str] = set()

    for i, result in enumerate(sub_question_answer_results, 1):
        question_level, _ = parse_question_id(result.question_id)
        sub_questions.append(result.question)

        if (
            result.verified_high_quality
            and result.answer
            and result.answer != UNKNOWN_ANSWER
        ):
            sub_question_type = "initial" if question_level == 0 else "refined"
            question_set = (
                initial_answered_sub_questions
                if question_level == 0
                else refined_answered_sub_questions
            )
            question_set.add(result.question)

            answered_sub_question_answer_list.append(
                SUB_QUESTION_ANSWER_TEMPLATE_REFINED.format(
                    sub_question=result.question,
                    sub_answer=result.answer,
                    sub_question_num=i,
                    sub_question_type=sub_question_type,
                )
            )

    # Calculate efficiency
    total_answered_questions = (
        initial_answered_sub_questions | refined_answered_sub_questions
    )
    revision_question_efficiency = (
        len(total_answered_questions) / len(initial_answered_sub_questions)
        if initial_answered_sub_questions
        else 10.0
        if refined_answered_sub_questions
        else 1.0
    )

    sub_question_answer_str = "\n\n------\n\n".join(
        set(answered_sub_question_answer_list)
    )
    initial_answer = state.initial_answer or ""

    # Choose appropriate prompt template
    base_prompt = (
        REFINED_ANSWER_PROMPT_W_SUB_QUESTIONS
        if answered_sub_question_answer_list
        else REFINED_ANSWER_PROMPT_WO_SUB_QUESTIONS
    )

    model = graph_config.tooling.fast_llm
    relevant_docs_str = format_docs(relevant_docs)
    relevant_docs_str = trim_prompt_piece(
        model.config,
        relevant_docs_str,
        base_prompt
        + question
        + sub_question_answer_str
        + initial_answer
        + persona_contextualized_prompt
        + prompt_enrichment_components.history,
    )

    msg = [
        HumanMessage(
            content=base_prompt.format(
                question=question,
                history=prompt_enrichment_components.history,
                answered_sub_questions=remove_document_citations(
                    sub_question_answer_str
                ),
                relevant_docs=relevant_docs_str,
                initial_answer=remove_document_citations(initial_answer)
                if initial_answer
                else None,
                persona_specification=persona_contextualized_prompt,
                date_prompt=prompt_enrichment_components.date_str,
            )
        )
    ]

    streamed_tokens: list[str | list[str | dict[str, Any]]] = [""]
    dispatch_timings: list[float] = []
    for message in model.stream(msg):
        # TODO: in principle, the answer here COULD contain images, but we don't support that yet
        content = message.content
        if not isinstance(content, str):
            raise ValueError(
                f"Expected content to be a string, but got {type(content)}"
            )

        start_stream_token = datetime.now()
        write_custom_event(
            "refined_agent_answer",
            AgentAnswerPiece(
                answer_piece=content,
                level=1,
                level_question_num=0,
                answer_type="agent_level_answer",
            ),
            writer,
        )
        end_stream_token = datetime.now()
        dispatch_timings.append((end_stream_token - start_stream_token).microseconds)
        streamed_tokens.append(content)

    logger.debug(
        f"Average dispatch time for refined answer: {sum(dispatch_timings) / len(dispatch_timings)}"
    )
    dispatch_main_answer_stop_info(1, writer)
    response = merge_content(*streamed_tokens)
    answer = cast(str, response)

    refined_agent_stats = RefinedAgentStats(
        revision_doc_efficiency=refined_doc_effectiveness,
        revision_question_efficiency=revision_question_efficiency,
    )

    logger.debug(f"\n\n---INITIAL ANSWER ---\n\n Answer:\n Agent: {initial_answer}")
    logger.debug("-" * 10)
    logger.debug(f"\n\n---REVISED AGENT ANSWER ---\n\n Answer:\n Agent: {answer}")

    logger.debug("-" * 100)

    if state.initial_agent_stats:
        initial_doc_boost_factor = state.initial_agent_stats.agent_effectiveness.get(
            "utilized_chunk_ratio", "--"
        )
        initial_support_boost_factor = (
            state.initial_agent_stats.agent_effectiveness.get("support_ratio", "--")
        )
        num_initial_verified_docs = state.initial_agent_stats.original_question.get(
            "num_verified_documents", "--"
        )
        initial_verified_docs_avg_score = (
            state.initial_agent_stats.original_question.get("verified_avg_score", "--")
        )
        initial_sub_questions_verified_docs = (
            state.initial_agent_stats.sub_questions.get("num_verified_documents", "--")
        )

        logger.debug("INITIAL AGENT STATS")
        logger.debug(f"Document Boost Factor: {initial_doc_boost_factor}")
        logger.debug(f"Support Boost Factor: {initial_support_boost_factor}")
        logger.debug(f"Originally Verified Docs: {num_initial_verified_docs}")
        logger.debug(
            f"Originally Verified Docs Avg Score: {initial_verified_docs_avg_score}"
        )
        logger.debug(
            f"Sub-Questions Verified Docs: {initial_sub_questions_verified_docs}"
        )
    if refined_agent_stats:
        logger.debug("-" * 10)
        logger.debug("REFINED AGENT STATS")
        logger.debug(
            f"Revision Doc Factor: {refined_agent_stats.revision_doc_efficiency}"
        )
        logger.debug(
            f"Revision Question Factor: {refined_agent_stats.revision_question_efficiency}"
        )

    agent_refined_end_time = datetime.now()
    if state.agent_refined_start_time:
        agent_refined_duration = (
            agent_refined_end_time - state.agent_refined_start_time
        ).total_seconds()
    else:
        agent_refined_duration = None

    agent_refined_metrics = AgentRefinedMetrics(
        refined_doc_boost_factor=refined_agent_stats.revision_doc_efficiency,
        refined_question_boost_factor=refined_agent_stats.revision_question_efficiency,
        duration_s=agent_refined_duration,
    )

    return RefinedAnswerUpdate(
        refined_answer=answer,
        refined_answer_quality=True,  # TODO: replace this with the actual check value
        refined_agent_stats=refined_agent_stats,
        agent_refined_end_time=agent_refined_end_time,
        agent_refined_metrics=agent_refined_metrics,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="generate refined answer",
                node_start_time=node_start_time,
            )
        ],
    )
