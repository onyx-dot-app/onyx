from datetime import datetime
from typing import cast

from langchain_core.messages import merge_message_runs
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    AnswerQuestionState,
)
from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    SubQuestionAnswerGenerationUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    build_sub_question_answer_prompt,
)
from onyx.agents.agent_search.shared_graph_utils.calculations import (
    dedup_sort_inference_section_list,
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
from onyx.agents.agent_search.shared_graph_utils.constants import (
    LLM_ANSWER_ERROR_MESSAGE,
)
from onyx.agents.agent_search.shared_graph_utils.llm import stream_llm_answer
from onyx.agents.agent_search.shared_graph_utils.models import AgentErrorLog
from onyx.agents.agent_search.shared_graph_utils.models import LLMNodeErrorStrings
from onyx.agents.agent_search.shared_graph_utils.utils import get_answer_citation_ids
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_persona_agent_prompt_expressions,
)
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import StreamType
from onyx.configs.agent_configs import AGENT_MAX_ANSWER_CONTEXT_DOCS
from onyx.configs.agent_configs import AGENT_MAX_TOKENS_SUBANSWER_GENERATION
from onyx.configs.agent_configs import AGENT_TIMEOUT_CONNECT_LLM_SUBANSWER_GENERATION
from onyx.configs.agent_configs import AGENT_TIMEOUT_LLM_SUBANSWER_GENERATION
from onyx.llm.chat_llm import LLMRateLimitError
from onyx.llm.chat_llm import LLMTimeoutError
from onyx.prompts.agent_search import NO_RECOVERED_DOCS
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.timing import log_function_time

logger = setup_logger()

_llm_node_error_strings = LLMNodeErrorStrings(
    timeout="LLM Timeout Error. A sub-answer could not be constructed and the sub-question will be ignored.",
    rate_limit="LLM Rate Limit Error. A sub-answer could not be constructed and the sub-question will be ignored.",
    general_error="General LLM Error. A sub-answer could not be constructed and the sub-question will be ignored.",
)


@log_function_time(print_only=True)
def generate_sub_answer(
    state: AnswerQuestionState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubQuestionAnswerGenerationUpdate:
    """
    LangGraph node to generate a sub-answer.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = state.question
    state.verified_reranked_documents
    level, question_num = parse_question_id(state.question_id)
    context_docs = state.context_documents[:AGENT_MAX_ANSWER_CONTEXT_DOCS]

    context_docs = dedup_sort_inference_section_list(context_docs)

    persona_contextualized_prompt = get_persona_agent_prompt_expressions(
        graph_config.inputs.persona
    ).contextualized_prompt

    if len(context_docs) == 0:
        answer_str = NO_RECOVERED_DOCS
        cited_documents: list = []
        log_results = "No documents retrieved"
        write_custom_event(
            "sub_answers",
            AgentAnswerPiece(
                answer_piece=answer_str,
                level=level,
                level_question_num=question_num,
                answer_type="agent_sub_answer",
            ),
            writer,
        )
    else:
        fast_llm = graph_config.tooling.fast_llm
        msg = build_sub_question_answer_prompt(
            question=question,
            original_question=graph_config.inputs.prompt_builder.raw_user_query,
            docs=context_docs,
            persona_specification=persona_contextualized_prompt,
            config=fast_llm.config,
        )

        agent_error: AgentErrorLog | None = None
        response: list[str] = []

        try:
            response, _ = run_with_timeout(
                AGENT_TIMEOUT_LLM_SUBANSWER_GENERATION,
                lambda: stream_llm_answer(
                    llm=fast_llm,
                    prompt=msg,
                    event_name="sub_answers",
                    writer=writer,
                    agent_answer_level=level,
                    agent_answer_question_num=question_num,
                    agent_answer_type="agent_sub_answer",
                    timeout_override=AGENT_TIMEOUT_CONNECT_LLM_SUBANSWER_GENERATION,
                    max_tokens=AGENT_MAX_TOKENS_SUBANSWER_GENERATION,
                ),
            )

        except (LLMTimeoutError, TimeoutError):
            agent_error = AgentErrorLog(
                error_type=AgentLLMErrorType.TIMEOUT,
                error_message=AGENT_LLM_TIMEOUT_MESSAGE,
                error_result=_llm_node_error_strings.timeout,
            )
            logger.error("LLM Timeout Error - generate sub answer")
        except LLMRateLimitError:
            agent_error = AgentErrorLog(
                error_type=AgentLLMErrorType.RATE_LIMIT,
                error_message=AGENT_LLM_RATELIMIT_MESSAGE,
                error_result=_llm_node_error_strings.rate_limit,
            )
            logger.error("LLM Rate Limit Error - generate sub answer")

        if agent_error:
            answer_str = LLM_ANSWER_ERROR_MESSAGE
            cited_documents = []
            log_results = (
                agent_error.error_result
                or "Sub-answer generation failed due to LLM error"
            )

        else:
            answer_str = merge_message_runs(response, chunk_separator="")[0].content
            answer_citation_ids = get_answer_citation_ids(answer_str)
            cited_documents = [
                context_docs[id] for id in answer_citation_ids if id < len(context_docs)
            ]
            log_results = None

    stop_event = StreamStopInfo(
        stop_reason=StreamStopReason.FINISHED,
        stream_type=StreamType.SUB_ANSWER,
        level=level,
        level_question_num=question_num,
    )
    write_custom_event("stream_finished", stop_event, writer)

    return SubQuestionAnswerGenerationUpdate(
        answer=answer_str,
        cited_documents=cited_documents,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="initial - generate individual sub answer",
                node_name="generate sub answer",
                node_start_time=node_start_time,
                result=log_results or "",
            )
        ],
    )
