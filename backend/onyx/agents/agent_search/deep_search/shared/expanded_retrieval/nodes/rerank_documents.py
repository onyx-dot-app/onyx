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
from onyx.context.search.models import RerankingDetails
from onyx.context.search.postprocessing.postprocessing import rerank_sections
from onyx.context.search.postprocessing.postprocessing import should_rerank
from onyx.db.engine import get_session_context_manager
from onyx.db.search_settings import get_current_search_settings
from onyx.utils.timing import log_function_time


@log_function_time(print_only=True)
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

    # Note that these are passed in values from the API and are overrides which are typically None
    rerank_settings = graph_config.inputs.search_request.rerank_settings
    allow_agent_reranking = graph_config.behavior.allow_agent_reranking

    if rerank_settings is None:
        with get_session_context_manager() as db_session:
            search_settings = get_current_search_settings(db_session)
            if not search_settings.disable_rerank_for_streaming:
                rerank_settings = RerankingDetails.from_db_model(search_settings)

    # Initial default: no reranking. Will be overwritten below if reranking is warranted
    reranked_documents = verified_documents

    if should_rerank(rerank_settings) and len(verified_documents) > 0:
        if len(verified_documents) > 1:
            if not allow_agent_reranking:
                logger.info("Use of local rerank model without GPU, skipping reranking")
            # No reranking, stay with verified_documents as default

            else:
                # Reranking is warranted, use the rerank_sections functon
                reranked_documents = rerank_sections(
                    query_str=question,
                    # if runnable, then rerank_settings is not None
                    rerank_settings=cast(RerankingDetails, rerank_settings),
                    sections_to_rerank=verified_documents,
                )
        else:
            logger.warning(
                f"{len(verified_documents)} verified document(s) found, skipping reranking"
            )
            # No reranking, stay with verified_documents as default
    else:
        logger.warning("No reranking settings found, using unranked documents")
        # No reranking, stay with verified_documents as default
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
