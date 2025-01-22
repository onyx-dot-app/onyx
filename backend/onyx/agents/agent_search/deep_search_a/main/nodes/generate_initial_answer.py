from datetime import datetime
from typing import Any
from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.deep_search_a.main.models import AgentBaseMetrics
from onyx.agents.agent_search.deep_search_a.main.operations import (
    calculate_initial_agent_stats,
)
from onyx.agents.agent_search.deep_search_a.main.operations import get_query_info
from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.operations import (
    remove_document_citations,
)
from onyx.agents.agent_search.deep_search_a.main.states import InitialAnswerUpdate
from onyx.agents.agent_search.deep_search_a.main.states import MainState
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_history_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.models import InitialAgentResultStats
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_DEFAULT,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    ASSISTANT_SYSTEM_PROMPT_PERSONA,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import INITIAL_RAG_PROMPT
from onyx.agents.agent_search.shared_graph_utils.prompts import (
    INITIAL_RAG_PROMPT_NO_SUB_QUESTIONS,
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


def generate_initial_answer(
    state: MainState, config: RunnableConfig
) -> InitialAnswerUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------GENERATE INITIAL---")

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = agent_a_config.search_request.query
    persona_prompt = get_persona_prompt(agent_a_config.search_request.persona)

    history = build_history_prompt(agent_a_config.message_history)

    sub_question_docs = state.documents
    all_original_question_documents = state.all_original_question_documents

    relevant_docs = dedup_inference_sections(
        sub_question_docs, all_original_question_documents
    )
    decomp_questions = []

    if len(relevant_docs) == 0:
        dispatch_custom_event(
            "initial_agent_answer",
            AgentAnswerPiece(
                answer_piece=UNKNOWN_ANSWER,
                level=0,
                level_question_nr=0,
                answer_type="agent_level_answer",
            ),
        )

        answer = UNKNOWN_ANSWER
        initial_agent_stats = InitialAgentResultStats(
            sub_questions={},
            original_question={},
            agent_effectiveness={},
        )

    else:
        # Use the query info from the base document retrieval
        query_info = get_query_info(state.original_question_retrieval_results)

        for tool_response in yield_search_responses(
            query=question,
            reranked_sections=relevant_docs,
            final_context_sections=relevant_docs,
            search_query_info=query_info,
            get_section_relevance=lambda: None,  # TODO: add relevance
            search_tool=agent_a_config.search_tool,
        ):
            dispatch_custom_event(
                "tool_response",
                ExtendedToolResponse(
                    id=tool_response.id,
                    response=tool_response.response,
                    level=0,
                    level_question_nr=0,  # 0, 0 is the base question
                ),
            )

        net_new_original_question_docs = []
        for all_original_question_doc in all_original_question_documents:
            if all_original_question_doc not in sub_question_docs:
                net_new_original_question_docs.append(all_original_question_doc)

        decomp_answer_results = state.decomp_answer_results

        good_qa_list: list[str] = []

        sub_question_nr = 1

        for decomp_answer_result in decomp_answer_results:
            decomp_questions.append(decomp_answer_result.question)
            _, question_nr = parse_question_id(decomp_answer_result.question_id)
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
            sub_question_nr += 1

        if len(good_qa_list) > 0:
            sub_question_answer_str = "\n\n------\n\n".join(good_qa_list)
        else:
            sub_question_answer_str = ""

        # Determine which persona-specification prompt to use

        if len(persona_prompt) == 0:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_DEFAULT
        else:
            persona_specification = ASSISTANT_SYSTEM_PROMPT_PERSONA.format(
                persona_prompt=persona_prompt
            )

        # Determine which base prompt to use given the sub-question information
        if len(good_qa_list) > 0:
            base_prompt = INITIAL_RAG_PROMPT
        else:
            base_prompt = INITIAL_RAG_PROMPT_NO_SUB_QUESTIONS

        model = agent_a_config.fast_llm

        doc_context = format_docs(relevant_docs)
        doc_context = trim_prompt_piece(
            model.config,
            doc_context,
            base_prompt + sub_question_answer_str + persona_specification + history,
        )

        msg = [
            HumanMessage(
                content=base_prompt.format(
                    question=question,
                    answered_sub_questions=remove_document_citations(
                        sub_question_answer_str
                    ),
                    relevant_docs=format_docs(relevant_docs),
                    persona_specification=persona_specification,
                    history=history,
                )
            )
        ]

        streamed_tokens: list[str | list[str | dict[str, Any]]] = [""]
        for message in model.stream(msg):
            # TODO: in principle, the answer here COULD contain images, but we don't support that yet
            content = message.content
            if not isinstance(content, str):
                raise ValueError(
                    f"Expected content to be a string, but got {type(content)}"
                )
            dispatch_custom_event(
                "initial_agent_answer",
                AgentAnswerPiece(
                    answer_piece=content,
                    level=0,
                    level_question_nr=0,
                    answer_type="agent_level_answer",
                ),
            )
            streamed_tokens.append(content)

        response = merge_content(*streamed_tokens)
        answer = cast(str, response)

        initial_agent_stats = calculate_initial_agent_stats(
            state.decomp_answer_results, state.original_question_retrieval_stats
        )

        logger.debug(
            f"\n\nYYYYY--Sub-Questions:\n\n{sub_question_answer_str}\n\nStats:\n\n"
        )

        if initial_agent_stats:
            logger.debug(initial_agent_stats.original_question)
            logger.debug(initial_agent_stats.sub_questions)
            logger.debug(initial_agent_stats.agent_effectiveness)

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INITIAL AGENT ANSWER  END---\n\n"
    )

    agent_base_end_time = datetime.now()

    agent_base_metrics = AgentBaseMetrics(
        num_verified_documents_total=len(relevant_docs),
        num_verified_documents_core=state.original_question_retrieval_stats.verified_count,
        verified_avg_score_core=state.original_question_retrieval_stats.verified_avg_scores,
        num_verified_documents_base=initial_agent_stats.sub_questions.get(
            "num_verified_documents", None
        ),
        verified_avg_score_base=initial_agent_stats.sub_questions.get(
            "verified_avg_score", None
        ),
        base_doc_boost_factor=initial_agent_stats.agent_effectiveness.get(
            "utilized_chunk_ratio", None
        ),
        support_boost_factor=initial_agent_stats.agent_effectiveness.get(
            "support_ratio", None
        ),
        duration__s=(agent_base_end_time - state.agent_start_time).total_seconds(),
    )

    return InitialAnswerUpdate(
        initial_answer=answer,
        initial_agent_stats=initial_agent_stats,
        generated_sub_questions=decomp_questions,
        agent_base_end_time=agent_base_end_time,
        agent_base_metrics=agent_base_metrics,
        log_messages=[
            f"{now_start} -- Initial answer generation - Time taken: {now_end - now_start}"
        ],
    )
