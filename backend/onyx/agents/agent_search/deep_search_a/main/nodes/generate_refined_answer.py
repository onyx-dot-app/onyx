from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.models import AgentRefinedMetrics
from onyx.agents.agent_search.deep_search_a.main.operations import get_query_info
from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.operations import (
    remove_document_citations,
)
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.deep_search_a.main.states import RefinedAnswerUpdate
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_history_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.models import RefinedAgentStats
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_DEFAULT,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_PERSONA,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import REVISED_RAG_PROMPT
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    REVISED_RAG_PROMPT_NO_SUB_QUESTIONS,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    SUB_QUESTION_ANSWER_TEMPLATE,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import UNKNOWN_ANSWER
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs
from onyx.agents.agent_search.shared_graph_utils.utils import get_persona_prompt
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import ExtendedToolResponse
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses


def generate_refined_answer(
    state: MainState, config: RunnableConfig
) -> RefinedAnswerUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE REFINED ANSWER---")

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = agent_a_config.search_request.query
    persona_prompt = get_persona_prompt(agent_a_config.search_request.persona)

    history = build_history_prompt(agent_a_config.prompt_builder)

    initial_documents = state.documents
    revised_documents = state.refined_documents

    combined_documents = dedup_inference_sections(initial_documents, revised_documents)

    query_info = get_query_info(state.original_question_retrieval_results)
    # stream refined answer docs
    for tool_response in yield_search_responses(
        query=question,
        reranked_sections=combined_documents,
        final_context_sections=combined_documents,
        search_query_info=query_info,
        get_section_relevance=lambda: None,  # TODO: add relevance
        search_tool=agent_a_config.search_tool,
    ):
        dispatch_custom_event(
            "tool_response",
            ExtendedToolResponse(
                id=tool_response.id,
                response=tool_response.response,
                level=1,
                level_question_nr=0,  # 0, 0 is the base question
            ),
        )

    if len(initial_documents) > 0:
        revision_doc_effectiveness = len(combined_documents) / len(initial_documents)
    elif len(revised_documents) == 0:
        revision_doc_effectiveness = 0.0
    else:
        revision_doc_effectiveness = 10.0

    decomp_answer_results = state.decomp_answer_results
    # revised_answer_results = state.refined_decomp_answer_results

    good_qa_list: list[str] = []
    decomp_questions = []

    initial_good_sub_questions: list[str] = []
    new_revised_good_sub_questions: list[str] = []

    sub_question_nr = 1

    for decomp_answer_result in decomp_answer_results:
        question_level, question_nr = parse_question_id(
            decomp_answer_result.question_id
        )

        decomp_questions.append(decomp_answer_result.question)
        if (
            decomp_answer_result.quality.lower().startswith("yes")
            and len(decomp_answer_result.answer) > 0
            and decomp_answer_result.answer != UNKNOWN_ANSWER
        ):
            good_qa_list.append(
                SUB_QUESTION_ANSWER_TEMPLATE.format(
                    sub_question=decomp_answer_result.question,
                    sub_answer=decomp_answer_result.answer,
                    sub_question_nr=sub_question_nr,
                )
            )
            if question_level == 0:
                initial_good_sub_questions.append(decomp_answer_result.question)
            else:
                new_revised_good_sub_questions.append(decomp_answer_result.question)

        sub_question_nr += 1

    initial_good_sub_questions = list(set(initial_good_sub_questions))
    new_revised_good_sub_questions = list(set(new_revised_good_sub_questions))
    total_good_sub_questions = list(
        set(initial_good_sub_questions + new_revised_good_sub_questions)
    )
    if len(initial_good_sub_questions) > 0:
        revision_question_efficiency: float = len(total_good_sub_questions) / len(
            initial_good_sub_questions
        )
    elif len(new_revised_good_sub_questions) > 0:
        revision_question_efficiency = 10.0
    else:
        revision_question_efficiency = 1.0

    sub_question_answer_str = "\n\n------\n\n".join(list(set(good_qa_list)))

    # original answer

    initial_answer = state.initial_answer

    # Determine which persona-specification prompt to use

    if len(persona_prompt) == 0:
        persona_specification = ASSISTANT_SYSTEM_PROMPT_DEFAULT
    else:
        persona_specification = ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
            persona_prompt=persona_prompt
        )

    # Determine which base prompt to use given the sub-question information
    if len(good_qa_list) > 0:
        base_prompt = REVISED_RAG_PROMPT
    else:
        base_prompt = REVISED_RAG_PROMPT_NO_SUB_QUESTIONS

    model = agent_a_config.fast_llm
    relevant_docs = format_docs(combined_documents)
    relevant_docs = trim_prompt_piece(
        model.config,
        relevant_docs,
        base_prompt
        + question
        + sub_question_answer_str
        + relevant_docs
        + initial_answer
        + persona_specification
        + history,
    )

    msg = [
        HumanMessage(
            content=base_prompt.format(
                question=question,
                history=history,
                answered_sub_questions=remove_document_citations(
                    sub_question_answer_str
                ),
                relevant_docs=relevant_docs,
                initial_answer=remove_document_citations(initial_answer),
                persona_specification=persona_specification,
            )
        )
    ]

    # Grader

    streamed_tokens: list[str | list[str | dict[str, Any]]] = [""]
    for message in model.stream(msg):
        # TODO: in principle, the answer here COULD contain images, but we don't support that yet
        content = message.content
        if not isinstance(content, str):
            raise ValueError(
                f"Expected content to be a string, but got {type(content)}"
            )
        dispatch_custom_event(
            "refined_agent_answer",
            AgentAnswerPiece(
                answer_piece=content,
                level=1,
                level_question_nr=0,
                answer_type="agent_level_answer",
            ),
        )
        streamed_tokens.append(content)

    response = merge_content(*streamed_tokens)
    answer = cast(str, response)

    # refined_agent_stats = _calculate_refined_agent_stats(
    #     state.decomp_answer_results, state.original_question_retrieval_stats
    # )

    initial_good_sub_questions_str = "\n".join(list(set(initial_good_sub_questions)))
    new_revised_good_sub_questions_str = "\n".join(
        list(set(new_revised_good_sub_questions))
    )

    refined_agent_stats = RefinedAgentStats(
        revision_doc_efficiency=revision_doc_effectiveness,
        revision_question_efficiency=revision_question_efficiency,
    )

    logger.debug(
        f"\n\n---INITIAL ANSWER START---\n\n Answer:\n Agent: {initial_answer}"
    )
    logger.debug("-" * 10)
    logger.debug(f"\n\n---REVISED AGENT ANSWER START---\n\n Answer:\n Agent: {answer}")

    logger.debug("-" * 100)
    logger.debug(f"\n\nINITAL Sub-Questions\n\n{initial_good_sub_questions_str}\n\n")
    logger.debug("-" * 10)
    logger.debug(
        f"\n\nNEW REVISED Sub-Questions\n\n{new_revised_good_sub_questions_str}\n\n"
    )

    logger.debug("-" * 100)

    logger.debug(
        f"\n\nINITAL & REVISED Sub-Questions & Answers:\n\n{sub_question_answer_str}\n\nStas:\n\n"
    )

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

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL AGENT ANSWER  END---\n\n"
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
        duration__s=agent_refined_duration,
    )

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------REFINED ANSWER UPDATE END---"
    )

    return RefinedAnswerUpdate(
        refined_answer=answer,
        refined_answer_quality=True,  # TODO: replace this with the actual check value
        refined_agent_stats=refined_agent_stats,
        agent_refined_end_time=agent_refined_end_time,
        agent_refined_metrics=agent_refined_metrics,
    )
