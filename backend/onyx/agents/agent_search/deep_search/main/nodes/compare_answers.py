from datetime import datetime
from typing import cast

from langchain_core.messages import BaseMessage
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.main.states import (
    InitialRefinedAnswerComparisonUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    binary_string_test,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_LLM_RATELIMIT_MESSAGE,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_LLM_TIMEOUT_MESSAGE,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_POSITIVE_VALUE_STR,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AgentLLMErrorType,
)
from onyx.agents.agent_search.shared_graph_utils.models import AgentErrorLog
from onyx.agents.agent_search.shared_graph_utils.models import LLMNodeErrorStrings
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import RefinedAnswerImprovement
from onyx.configs.agent_configs import AGENT_TIMEOUT_CONNECT_LLM_COMPARE_ANSWERS
from onyx.configs.agent_configs import AGENT_TIMEOUT_LLM_COMPARE_ANSWERS
from onyx.llm.chat_llm import LLMRateLimitError
from onyx.llm.chat_llm import LLMTimeoutError
from onyx.prompts.agent_search import (
    INITIAL_REFINED_ANSWER_COMPARISON_PROMPT,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.timing import log_function_time

logger = setup_logger()

_llm_node_error_strings = LLMNodeErrorStrings(
    timeout="The LLM timed out, and the answers could not be compared.",
    rate_limit="The LLM encountered a rate limit, and the answers could not be compared.",
    general_error="The LLM encountered an error, and the answers could not be compared.",
)

_ANSWER_QUALITY_NOT_SUFFICIENT_MESSAGE = (
    "Answer quality is not sufficient, so stay with the initial answer."
)


@log_function_time(print_only=True)
def compare_answers(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> InitialRefinedAnswerComparisonUpdate:
    """
    LangGraph node to compare the initial answer and the refined answer and determine if the
    refined answer is sufficiently better than the initial answer.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.search_request.query
    initial_answer = state.initial_answer
    refined_answer = state.refined_answer

    # if answer quality is not sufficient, then stay with the initial answer
    if not state.refined_answer_quality:
        write_custom_event(
            "refined_answer_improvement",
            RefinedAnswerImprovement(
                refined_answer_improvement=False,
            ),
            writer,
        )

        return InitialRefinedAnswerComparisonUpdate(
            refined_answer_improvement_eval=False,
            log_messages=[
                get_langgraph_node_log_string(
                    graph_component="main",
                    node_name="compare answers",
                    node_start_time=node_start_time,
                    result=_ANSWER_QUALITY_NOT_SUFFICIENT_MESSAGE,
                )
            ],
        )

    compare_answers_prompt = INITIAL_REFINED_ANSWER_COMPARISON_PROMPT.format(
        question=question, initial_answer=initial_answer, refined_answer=refined_answer
    )

    msg = [HumanMessage(content=compare_answers_prompt)]

    agent_error: AgentErrorLog | None = None
    # Get the rewritten queries in a defined format
    model = graph_config.tooling.fast_llm
    resp: BaseMessage | None = None
    refined_answer_improvement: bool | None = None
    # no need to stream this
    try:
        resp = run_with_timeout(
            AGENT_TIMEOUT_LLM_COMPARE_ANSWERS,
            model.invoke,
            prompt=msg,
            timeout_override=AGENT_TIMEOUT_CONNECT_LLM_COMPARE_ANSWERS,
        )

    except (LLMTimeoutError, TimeoutError):
        agent_error = AgentErrorLog(
            error_type=AgentLLMErrorType.TIMEOUT,
            error_message=AGENT_LLM_TIMEOUT_MESSAGE,
            error_result=_llm_node_error_strings.timeout,
        )
        logger.error("LLM Timeout Error - compare answers")
        # continue as True in this support step
    except LLMRateLimitError:
        agent_error = AgentErrorLog(
            error_type=AgentLLMErrorType.RATE_LIMIT,
            error_message=AGENT_LLM_RATELIMIT_MESSAGE,
            error_result=_llm_node_error_strings.rate_limit,
        )
        logger.error("LLM Rate Limit Error - compare answers")
        # continue as True in this support step

    if agent_error or resp is None:
        refined_answer_improvement = True
        if agent_error:
            log_result = agent_error.error_result
        else:
            log_result = "An answer could not be generated."

    else:
        refined_answer_improvement = binary_string_test(
            text=cast(str, resp.content),
            positive_value=AGENT_POSITIVE_VALUE_STR,
        )
        log_result = f"Answer comparison: {refined_answer_improvement}"

    write_custom_event(
        "refined_answer_improvement",
        RefinedAnswerImprovement(
            refined_answer_improvement=refined_answer_improvement,
        ),
        writer,
    )

    return InitialRefinedAnswerComparisonUpdate(
        refined_answer_improvement_eval=refined_answer_improvement,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="compare answers",
                node_start_time=node_start_time,
                result=log_result,
            )
        ],
    )
