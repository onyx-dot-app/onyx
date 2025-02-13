from datetime import datetime
from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.operations import (
    logger,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    DocRerankingUpdate,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.calculations import get_fit_scores
from onyx.agents.agent_search.shared_graph_utils.models import RetrievalFitStats
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.agent_configs import AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS
from onyx.configs.agent_configs import AGENT_RERANKING_STATS
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchRequest
from onyx.context.search.postprocessing.postprocessing import rerank_sections


def rerank_documents(
    state: ExpandedRetrievalState, config: RunnableConfig
) -> DocRerankingUpdate:
    """
    LangGraph node to rerank the retrieved and verified documents. A part of the
    pre-existing pipeline is used here.
    """
    node_start_time = datetime.now()
    verified_documents = state.verified_documents

    # Rerank post retrieval and verification. First, create a search query
    # then create the list of reranked sections
    # If no question defined/question is None in the state, use the original
    # question from the search request as query

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = (
        state.question if state.question else graph_config.inputs.search_request.query
    )
    assert (
        graph_config.tooling.search_tool
    ), "search_tool must be provided for agentic search"

    search_request = SearchRequest(
        query=question,
        persona=graph_config.inputs.search_request.persona,
        rerank_settings=graph_config.inputs.search_request.rerank_settings,
    )

    if (
        search_request.rerank_settings
        and search_request.rerank_settings.rerank_model_name
        and search_request.rerank_settings.num_rerank > 0
        and len(verified_documents) > 0
    ):
        if len(verified_documents) > 1:
            reranked_documents = rerank_sections(
                query_str=question,
                rerank_settings=search_request.rerank_settings,
                sections_to_rerank=verified_documents,
            )
        else:
            num = "No" if len(verified_documents) == 0 else "One"
            logger.warning(f"{num} verified document(s) found, skipping reranking")
            reranked_documents = verified_documents
    else:
        logger.warning("No reranking settings found, using unranked documents")
        reranked_documents = verified_documents

    if AGENT_RERANKING_STATS:
        fit_scores = get_fit_scores(verified_documents, reranked_documents)
    else:
        fit_scores = RetrievalFitStats(fit_score_lift=0, rerank_effect=0, fit_scores={})

    return DocRerankingUpdate(
        reranked_documents=[
            doc for doc in reranked_documents if type(doc) == InferenceSection
        ][:AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS],
        sub_question_retrieval_stats=fit_scores,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="shared - expanded retrieval",
                node_name="rerank documents",
                node_start_time=node_start_time,
            )
        ],
    )
