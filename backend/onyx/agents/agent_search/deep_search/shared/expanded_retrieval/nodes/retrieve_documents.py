from datetime import datetime
from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.operations import (
    logger,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    DocRetrievalUpdate,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    RetrievalInput,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.calculations import get_fit_scores
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.agent_configs import AGENT_MAX_QUERY_RETRIEVAL_RESULTS
from onyx.configs.agent_configs import AGENT_RETRIEVAL_STATS
from onyx.context.search.models import InferenceSection
from onyx.db.engine import get_session_context_manager
from onyx.tools.models import SearchQueryInfo
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.utils.timing import log_function_time


@log_function_time(print_only=True)
def retrieve_documents(
    state: RetrievalInput, config: RunnableConfig
) -> DocRetrievalUpdate:
    """
    LangGraph node to retrieve documents from the search tool.
    """
    node_start_time = datetime.now()
    query_to_retrieve = state.query_to_retrieve
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    search_tool = graph_config.tooling.search_tool

    retrieved_docs: list[InferenceSection] = []
    if not query_to_retrieve.strip():
        logger.warning("Empty query, skipping retrieval")

        return DocRetrievalUpdate(
            query_retrieval_results=[],
            retrieved_documents=[],
            log_messages=[
                get_langgraph_node_log_string(
                    graph_component="shared - expanded retrieval",
                    node_name="retrieve documents",
                    node_start_time=node_start_time,
                    result="Empty query, skipping retrieval",
                )
            ],
        )

    query_info = None
    if search_tool is None:
        raise ValueError("search_tool must be provided for agentic search")

    callback_container: list[list[InferenceSection]] = []

    # new db session to avoid concurrency issues
    with get_session_context_manager() as db_session:
        for tool_response in search_tool.run(
            query=query_to_retrieve,
            override_kwargs=SearchToolOverrideKwargs(
                force_no_rerank=True,
                alternate_db_session=db_session,
                retrieved_sections_callback=callback_container.append,
                skip_query_analysis=not state.base_search,
            ),
        ):
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections
                query_info = SearchQueryInfo(
                    predicted_search=response.predicted_search,
                    final_filters=response.final_filters,
                    recency_bias_multiplier=response.recency_bias_multiplier,
                )
                break

    retrieved_docs = retrieved_docs[:AGENT_MAX_QUERY_RETRIEVAL_RESULTS]

    if AGENT_RETRIEVAL_STATS:
        pre_rerank_docs = callback_container[0]
        fit_scores = get_fit_scores(
            pre_rerank_docs,
            retrieved_docs,
        )
    else:
        fit_scores = None

    expanded_retrieval_result = QueryRetrievalResult(
        query=query_to_retrieve,
        retrieved_documents=retrieved_docs,
        stats=fit_scores,
        query_info=query_info,
    )

    return DocRetrievalUpdate(
        query_retrieval_results=[expanded_retrieval_result],
        retrieved_documents=retrieved_docs,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="shared - expanded retrieval",
                node_name="retrieve documents",
                node_start_time=node_start_time,
            )
        ],
    )
