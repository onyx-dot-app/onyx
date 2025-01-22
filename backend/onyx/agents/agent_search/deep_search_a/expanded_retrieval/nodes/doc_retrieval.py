from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.operations import logger
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    DocRetrievalUpdate,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    RetrievalInput,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.calculations import get_fit_scores
from onyx.agents.agent_search.shared_graph_utils.models import QueryResult
from onyx.configs.dev_configs import AGENT_MAX_QUERY_RETRIEVAL_RESULTS
from onyx.configs.dev_configs import AGENT_RETRIEVAL_STATS
from onyx.context.search.models import InferenceSection
from onyx.db.engine import get_session_context_manager
from onyx.tools.models import SearchQueryInfo
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary


def doc_retrieval(state: RetrievalInput, config: RunnableConfig) -> DocRetrievalUpdate:
    """
    Retrieve documents

    Args:
        state (RetrievalInput): Primary state + the query to retrieve
        config (RunnableConfig): Configuration containing ProSearchConfig

    Updates:
        expanded_retrieval_results: list[ExpandedRetrievalResult]
        retrieved_documents: list[InferenceSection]
    """
    query_to_retrieve = state.query_to_retrieve
    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    search_tool = agent_a_config.search_tool

    retrieved_docs: list[InferenceSection] = []
    if not query_to_retrieve.strip():
        logger.warning("Empty query, skipping retrieval")
        return DocRetrievalUpdate(
            expanded_retrieval_results=[],
            retrieved_documents=[],
        )

    query_info = None
    # new db session to avoid concurrency issues
    with get_session_context_manager() as db_session:
        for tool_response in search_tool.run(
            query=query_to_retrieve,
            force_no_rerank=True,
            alternate_db_session=db_session,
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
    pre_rerank_docs = retrieved_docs
    if search_tool.search_pipeline is not None:
        pre_rerank_docs = (
            search_tool.search_pipeline._retrieved_sections or retrieved_docs
        )

    if AGENT_RETRIEVAL_STATS:
        fit_scores = get_fit_scores(
            pre_rerank_docs,
            retrieved_docs,
        )
    else:
        fit_scores = None

    expanded_retrieval_result = QueryResult(
        query=query_to_retrieve,
        search_results=retrieved_docs,
        stats=fit_scores,
        query_info=query_info,
    )
    return DocRetrievalUpdate(
        expanded_retrieval_results=[expanded_retrieval_result],
        retrieved_documents=retrieved_docs,
    )
