from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_content
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.initial.generate_initial_answer.states import (
    SubQuestionRetrievalState,
)
from onyx.agents.agent_search.deep_search.main.models import AgentBaseMetrics
from onyx.agents.agent_search.deep_search.main.operations import (
    calculate_initial_agent_stats,
)
from onyx.agents.agent_search.deep_search.main.operations import get_query_info
from onyx.agents.agent_search.deep_search.main.operations import logger
from onyx.agents.agent_search.deep_search.main.states import (
    InitialAnswerUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    get_prompt_enrichment_components,
)
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.calculations import (
    get_answer_generation_documents,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_LLM_RATELIMIT_MESSAGE,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_LLM_TIMEOUT_MESSAGE,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AgentLLMErrorType,
)
from onyx.agents.agent_search.shared_graph_utils.models import AgentErrorLog
from onyx.agents.agent_search.shared_graph_utils.models import InitialAgentResultStats
from onyx.agents.agent_search.shared_graph_utils.models import LLMNodeErrorStrings
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_section_list,
)
from onyx.agents.agent_search.shared_graph_utils.utils import _should_restrict_tokens
from onyx.agents.agent_search.shared_graph_utils.utils import (
    dispatch_main_answer_stop_info,
)
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_deduplicated_structured_subquestion_documents,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import relevance_from_docs
from onyx.agents.agent_search.shared_graph_utils.utils import remove_document_citations
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import ExtendedToolResponse
from onyx.chat.models import StreamingError
from onyx.configs.agent_configs import AGENT_ANSWER_GENERATION_BY_FAST_LLM
from onyx.configs.agent_configs import AGENT_MAX_ANSWER_CONTEXT_DOCS
from onyx.configs.agent_configs import AGENT_MAX_STREAMED_DOCS_FOR_INITIAL_ANSWER
from onyx.configs.agent_configs import AGENT_MAX_TOKENS_ANSWER_GENERATION
from onyx.configs.agent_configs import AGENT_MIN_ORIG_QUESTION_DOCS
from onyx.configs.agent_configs import (
    AGENT_TIMEOUT_CONNECT_LLM_INITIAL_ANSWER_GENERATION,
)
from onyx.configs.agent_configs import (
    AGENT_TIMEOUT_LLM_INITIAL_ANSWER_GENERATION,
)
from onyx.llm.chat_llm import LLMRateLimitError
from onyx.llm.chat_llm import LLMTimeoutError
from onyx.prompts.agent_search import INITIAL_ANSWER_PROMPT_W_SUB_QUESTIONS
from onyx.prompts.agent_search import (
    INITIAL_ANSWER_PROMPT_WO_SUB_QUESTIONS,
)
from onyx.prompts.agent_search import (
    SUB_QUESTION_ANSWER_TEMPLATE,
)
from onyx.prompts.agent_search import UNKNOWN_ANSWER
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.timing import log_function_time

_llm_node_error_strings = LLMNodeErrorStrings(
    timeout="LLM Timeout Error. The initial answer could not be generated.",
    rate_limit="LLM Rate Limit Error. The initial answer could not be generated.",
    general_error="General LLM Error. The initial answer could not be generated.",
)


@log_function_time(print_only=True)
def generate_initial_answer(
    state: SubQuestionRetrievalState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> InitialAnswerUpdate:
    """
    LangGraph node to generate the initial answer, using the initial sub-questions/sub-answers and the
    documents retrieved for the original question.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    prompt_enrichment_components = get_prompt_enrichment_components(graph_config)

    # get all documents cited in sub-questions
    structured_subquestion_docs = get_deduplicated_structured_subquestion_documents(
        state.sub_question_results
    )

    orig_question_retrieval_documents = state.orig_question_retrieved_documents

    consolidated_context_docs = structured_subquestion_docs.cited_documents
    counter = 0
    for original_doc in orig_question_retrieval_documents:
        if original_doc in structured_subquestion_docs.cited_documents:
            continue

        if (
            counter <= AGENT_MIN_ORIG_QUESTION_DOCS
            or len(consolidated_context_docs) < AGENT_MAX_ANSWER_CONTEXT_DOCS
        ):
            consolidated_context_docs.append(original_doc)
            counter += 1

    # sort docs by their scores - though the scores refer to different questions
    relevant_docs = dedup_inference_section_list(consolidated_context_docs)

    sub_questions: list[str] = []

    # Create the list of documents to stream out. Start with the
    # ones that wil be in the context (or, if len == 0, use docs
    # that were retrieved for the original question)
    answer_generation_documents = get_answer_generation_documents(
        relevant_docs=relevant_docs,
        context_documents=structured_subquestion_docs.context_documents,
        original_question_docs=orig_question_retrieval_documents,
        max_docs=AGENT_MAX_STREAMED_DOCS_FOR_INITIAL_ANSWER,
    )

    # Use the query info from the base document retrieval
    query_info = get_query_info(state.orig_question_sub_query_retrieval_results)

    assert (
        graph_config.tooling.search_tool
    ), "search_tool must be provided for agentic search"

    relevance_list = relevance_from_docs(
        answer_generation_documents.streaming_documents
    )
    for tool_response in yield_search_responses(
        query=question,
        get_retrieved_sections=lambda: answer_generation_documents.context_documents,
        get_final_context_sections=lambda: answer_generation_documents.context_documents,
        search_query_info=query_info,
        get_section_relevance=lambda: relevance_list,
        search_tool=graph_config.tooling.search_tool,
    ):
        write_custom_event(
            "tool_response",
            ExtendedToolResponse(
                id=tool_response.id,
                response=tool_response.response,
                level=0,
                level_question_num=0,  # 0, 0 is the base question
            ),
            writer,
        )

    if len(answer_generation_documents.context_documents) == 0:
        write_custom_event(
            "initial_agent_answer",
            AgentAnswerPiece(
                answer_piece=UNKNOWN_ANSWER,
                level=0,
                level_question_num=0,
                answer_type="agent_level_answer",
            ),
            writer,
        )
        dispatch_main_answer_stop_info(0, writer)

        answer = UNKNOWN_ANSWER
        initial_agent_stats = InitialAgentResultStats(
            sub_questions={},
            original_question={},
            agent_effectiveness={},
        )

    else:
        sub_question_answer_results = state.sub_question_results

        # Collect the sub-questions and sub-answers and construct an appropriate
        # prompt string.
        # Consider replacing by a function.
        answered_sub_questions: list[str] = []
        all_sub_questions: list[str] = []  # Separate list for tracking all questions

        for idx, sub_question_answer_result in enumerate(
            sub_question_answer_results, start=1
        ):
            all_sub_questions.append(sub_question_answer_result.question)

            is_valid_answer = (
                sub_question_answer_result.verified_high_quality
                and sub_question_answer_result.answer
                and sub_question_answer_result.answer != UNKNOWN_ANSWER
            )

            if is_valid_answer:
                answered_sub_questions.append(
                    SUB_QUESTION_ANSWER_TEMPLATE.format(
                        sub_question=sub_question_answer_result.question,
                        sub_answer=sub_question_answer_result.answer,
                        sub_question_num=idx,
                    )
                )

        sub_question_answer_str = (
            "\n\n------\n\n".join(answered_sub_questions)
            if answered_sub_questions
            else ""
        )

        # Use the appropriate prompt based on whether there are sub-questions.
        base_prompt = (
            INITIAL_ANSWER_PROMPT_W_SUB_QUESTIONS
            if answered_sub_questions
            else INITIAL_ANSWER_PROMPT_WO_SUB_QUESTIONS
        )

        sub_questions = all_sub_questions  # Replace the original assignment

        model = (
            graph_config.tooling.fast_llm
            if AGENT_ANSWER_GENERATION_BY_FAST_LLM
            else graph_config.tooling.primary_llm
        )

        doc_context = format_docs(answer_generation_documents.context_documents)
        doc_context = trim_prompt_piece(
            config=model.config,
            prompt_piece=doc_context,
            reserved_str=(
                base_prompt
                + sub_question_answer_str
                + prompt_enrichment_components.persona_prompts.contextualized_prompt
                + prompt_enrichment_components.history
                + prompt_enrichment_components.date_str
            ),
        )

        msg = [
            HumanMessage(
                content=base_prompt.format(
                    question=question,
                    answered_sub_questions=remove_document_citations(
                        sub_question_answer_str
                    ),
                    relevant_docs=doc_context,
                    persona_specification=prompt_enrichment_components.persona_prompts.contextualized_prompt,
                    history=prompt_enrichment_components.history,
                    date_prompt=prompt_enrichment_components.date_str,
                )
            )
        ]

        streamed_tokens: list[str] = [""]
        dispatch_timings: list[float] = []

        agent_error: AgentErrorLog | None = None

        def stream_initial_answer() -> list[str]:
            response: list[str] = []
            for message in model.stream(
                msg,
                timeout_override=AGENT_TIMEOUT_CONNECT_LLM_INITIAL_ANSWER_GENERATION,
                max_tokens=(
                    AGENT_MAX_TOKENS_ANSWER_GENERATION
                    if _should_restrict_tokens(model.config)
                    else None
                ),
            ):
                # TODO: in principle, the answer here COULD contain images, but we don't support that yet
                content = message.content
                if not isinstance(content, str):
                    raise ValueError(
                        f"Expected content to be a string, but got {type(content)}"
                    )
                start_stream_token = datetime.now()

                write_custom_event(
                    "initial_agent_answer",
                    AgentAnswerPiece(
                        answer_piece=content,
                        level=0,
                        level_question_num=0,
                        answer_type="agent_level_answer",
                    ),
                    writer,
                )
                end_stream_token = datetime.now()
                dispatch_timings.append(
                    (end_stream_token - start_stream_token).microseconds
                )
                response.append(content)
            return response

        try:
            streamed_tokens = run_with_timeout(
                AGENT_TIMEOUT_LLM_INITIAL_ANSWER_GENERATION,
                stream_initial_answer,
            )

        except (LLMTimeoutError, TimeoutError):
            agent_error = AgentErrorLog(
                error_type=AgentLLMErrorType.TIMEOUT,
                error_message=AGENT_LLM_TIMEOUT_MESSAGE,
                error_result=_llm_node_error_strings.timeout,
            )
            logger.error("LLM Timeout Error - generate initial answer")

        except LLMRateLimitError:
            agent_error = AgentErrorLog(
                error_type=AgentLLMErrorType.RATE_LIMIT,
                error_message=AGENT_LLM_RATELIMIT_MESSAGE,
                error_result=_llm_node_error_strings.rate_limit,
            )
            logger.error("LLM Rate Limit Error - generate initial answer")

        if agent_error:
            write_custom_event(
                "initial_agent_answer",
                StreamingError(
                    error=AGENT_LLM_TIMEOUT_MESSAGE,
                ),
                writer,
            )
            return InitialAnswerUpdate(
                initial_answer=None,
                answer_error=AgentErrorLog(
                    error_message=agent_error.error_message or "An LLM error occurred",
                    error_type=agent_error.error_type,
                    error_result=agent_error.error_result,
                ),
                initial_agent_stats=None,
                generated_sub_questions=sub_questions,
                agent_base_end_time=None,
                agent_base_metrics=None,
                log_messages=[
                    get_langgraph_node_log_string(
                        graph_component="initial - generate initial answer",
                        node_name="generate initial answer",
                        node_start_time=node_start_time,
                        result=agent_error.error_result or "An LLM error occurred",
                    )
                ],
            )

        logger.debug(
            f"Average dispatch time for initial answer: {sum(dispatch_timings) / len(dispatch_timings)}"
        )

        dispatch_main_answer_stop_info(0, writer)
        response = merge_content(*streamed_tokens)
        answer = cast(str, response)

        initial_agent_stats = calculate_initial_agent_stats(
            state.sub_question_results, state.orig_question_retrieval_stats
        )

        logger.debug(
            f"\n\nYYYYY--Sub-Questions:\n\n{sub_question_answer_str}\n\nStats:\n\n"
        )

        if initial_agent_stats:
            logger.debug(initial_agent_stats.original_question)
            logger.debug(initial_agent_stats.sub_questions)
            logger.debug(initial_agent_stats.agent_effectiveness)

    agent_base_end_time = datetime.now()

    if agent_base_end_time and state.agent_start_time:
        duration_s = (agent_base_end_time - state.agent_start_time).total_seconds()
    else:
        duration_s = None

    agent_base_metrics = AgentBaseMetrics(
        num_verified_documents_total=len(relevant_docs),
        num_verified_documents_core=state.orig_question_retrieval_stats.verified_count,
        verified_avg_score_core=state.orig_question_retrieval_stats.verified_avg_scores,
        num_verified_documents_base=initial_agent_stats.sub_questions.get(
            "num_verified_documents"
        ),
        verified_avg_score_base=initial_agent_stats.sub_questions.get(
            "verified_avg_score"
        ),
        base_doc_boost_factor=initial_agent_stats.agent_effectiveness.get(
            "utilized_chunk_ratio"
        ),
        support_boost_factor=initial_agent_stats.agent_effectiveness.get(
            "support_ratio"
        ),
        duration_s=duration_s,
    )

    return InitialAnswerUpdate(
        initial_answer=answer,
        initial_agent_stats=initial_agent_stats,
        generated_sub_questions=sub_questions,
        agent_base_end_time=agent_base_end_time,
        agent_base_metrics=agent_base_metrics,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="initial - generate initial answer",
                node_name="generate initial answer",
                node_start_time=node_start_time,
                result="",
            )
        ],
    )
