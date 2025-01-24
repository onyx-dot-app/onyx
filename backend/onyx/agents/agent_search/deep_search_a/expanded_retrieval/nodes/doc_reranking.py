from datetime import datetime
from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.operations import logger
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    DocRerankingUpdate,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.calculations import get_fit_scores
from onyx.agents.agent_search.shared_graph_utils.models import RetrievalFitStats
from onyx.configs.dev_configs import AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS
from onyx.configs.dev_configs import AGENT_RERANKING_STATS
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import SearchRequest
from onyx.context.search.pipeline import retrieval_preprocessing
from onyx.context.search.postprocessing.postprocessing import rerank_sections
from onyx.db.engine import get_session_context_manager


def doc_reranking(
    state: ExpandedRetrievalState, config: RunnableConfig
) -> DocRerankingUpdate:
    now_start = datetime.now()
    verified_documents = state.verified_documents

    # Rerank post retrieval and verification. First, create a search query
    # then create the list of reranked sections

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = state.question if state.question else agent_a_config.search_request.query
    with get_session_context_manager() as db_session:
        _search_query = retrieval_preprocessing(
            search_request=SearchRequest(query=question),
            user=agent_a_config.search_tool.user,  # bit of a hack
            llm=agent_a_config.fast_llm,
            db_session=db_session,
        )

    # skip section filtering

    if (
        _search_query.rerank_settings
        and _search_query.rerank_settings.rerank_model_name
        and _search_query.rerank_settings.num_rerank > 0
    ):
        reranked_documents = rerank_sections(
            _search_query,
            verified_documents,
        )
    else:
        logger.warning("No reranking settings found, using unranked documents")
        reranked_documents = verified_documents

    if AGENT_RERANKING_STATS:
        fit_scores = get_fit_scores(verified_documents, reranked_documents)
    else:
        fit_scores = RetrievalFitStats(fit_score_lift=0, rerank_effect=0, fit_scores={})

    # TODO: stream deduped docs here, or decide to use search tool ranking/verification
    now_end = datetime.now()
    return DocRerankingUpdate(
        reranked_documents=[
            doc for doc in reranked_documents if type(doc) == InferenceSection
        ][:AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS],
        sub_question_retrieval_stats=fit_scores,
        log_messages=[
            f"{now_end} -- Expanded Retrieval - Reranking - Time taken: {now_end - now_start}"
        ],
    )
