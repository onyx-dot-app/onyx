from datetime import datetime

from onyx.agents.agent_search.deep_search_a.base_raw_search.states import (
    BaseRawSearchOutput,
)
from onyx.agents.agent_search.deep_search_a.main.operations import logger
from onyx.agents.agent_search.deep_search_a.main.states import ExpandedRetrievalUpdate
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkStats


def ingest_initial_base_retrieval(
    state: BaseRawSearchOutput,
) -> ExpandedRetrievalUpdate:
    now_start = datetime.now()

    logger.debug(f"--------{now_start}--------INGEST INITIAL RETRIEVAL---")

    sub_question_retrieval_stats = (
        state.base_expanded_retrieval_result.sub_question_retrieval_stats
    )
    if sub_question_retrieval_stats is None:
        sub_question_retrieval_stats = AgentChunkStats()
    else:
        sub_question_retrieval_stats = sub_question_retrieval_stats

    now_end = datetime.now()

    logger.debug(
        f"--------{now_end}--{now_end - now_start}--------INGEST INITIAL RETRIEVAL END---"
    )

    return ExpandedRetrievalUpdate(
        original_question_retrieval_results=state.base_expanded_retrieval_result.expanded_queries_results,
        all_original_question_documents=state.base_expanded_retrieval_result.context_documents,
        original_question_retrieval_stats=sub_question_retrieval_stats,
        log_messages=[
            f"{now_end} -- Main - Ingestion base retrieval,  Time taken: {now_end - now_start}"
        ],
    )
