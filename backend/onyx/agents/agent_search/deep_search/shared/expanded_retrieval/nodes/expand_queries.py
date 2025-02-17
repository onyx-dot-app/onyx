from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_message_runs
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.operations import (
    dispatch_subquery,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    QueryExpansionUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
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
from onyx.agents.agent_search.shared_graph_utils.models import BaseMessage_Content
from onyx.agents.agent_search.shared_graph_utils.models import LLMNodeErrorStrings
from onyx.agents.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.configs.agent_configs import (
    AGENT_TIMEOUT_CONNECT_LLM_QUERY_REWRITING_GENERATION,
)
from onyx.configs.agent_configs import AGENT_TIMEOUT_LLM_QUERY_REWRITING_GENERATION
from onyx.llm.chat_llm import LLMRateLimitError
from onyx.llm.chat_llm import LLMTimeoutError
from onyx.prompts.agent_search import (
    QUERY_REWRITING_PROMPT,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.timing import log_function_time

logger = setup_logger()

_llm_node_error_strings = LLMNodeErrorStrings(
    timeout="Query rewriting failed due to LLM timeout - the original question will be used.",
    rate_limit="Query rewriting failed due to LLM rate limit - the original question will be used.",
    general_error="Query rewriting failed due to LLM error - the original question will be used.",
)


@log_function_time(print_only=True)
def expand_queries(
    state: ExpandedRetrievalInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> QueryExpansionUpdate:
    """
    LangGraph node to expand a question into multiple search queries.
    """
    # Sometimes we want to expand the original question, sometimes we want to expand a sub-question.
    # When we are running this node on the original question, no question is explictly passed in.
    # Instead, we use the original question from the search request.
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    node_start_time = datetime.now()
    question = state.question

    model = graph_config.tooling.fast_llm
    sub_question_id = state.sub_question_id
    if sub_question_id is None:
        level, question_num = 0, 0
    else:
        level, question_num = parse_question_id(sub_question_id)

    msg = [
        HumanMessage(
            content=QUERY_REWRITING_PROMPT.format(question=question),
        )
    ]

    agent_error: AgentErrorLog | None = None
    llm_response_list: list[BaseMessage_Content] = []
    llm_response = ""
    rewritten_queries = []

    try:
        llm_response_list = run_with_timeout(
            AGENT_TIMEOUT_LLM_QUERY_REWRITING_GENERATION,
            dispatch_separated,
            model.stream(
                prompt=msg,
                timeout_override=AGENT_TIMEOUT_CONNECT_LLM_QUERY_REWRITING_GENERATION,
            ),
            dispatch_subquery(level, question_num, writer),
        )
        llm_response = merge_message_runs(llm_response_list, chunk_separator="")[
            0
        ].content
        rewritten_queries = llm_response.split("\n")
        log_result = f"Number of expanded queries: {len(rewritten_queries)}"

    except (LLMTimeoutError, TimeoutError):
        agent_error = AgentErrorLog(
            error_type=AgentLLMErrorType.TIMEOUT,
            error_message=AGENT_LLM_TIMEOUT_MESSAGE,
            error_result=_llm_node_error_strings.timeout,
        )
        logger.error("LLM Timeout Error - expand queries")
        log_result = agent_error.error_result

    except LLMRateLimitError:
        agent_error = AgentErrorLog(
            error_type=AgentLLMErrorType.RATE_LIMIT,
            error_message=AGENT_LLM_RATELIMIT_MESSAGE,
            error_result=_llm_node_error_strings.rate_limit,
        )
        logger.error("LLM Rate Limit Error - expand queries")
        log_result = agent_error.error_result
    # use subquestion as query if query generation fails

    return QueryExpansionUpdate(
        expanded_queries=rewritten_queries,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="shared - expanded retrieval",
                node_name="expand queries",
                node_start_time=node_start_time,
                result=log_result,
            )
        ],
    )
