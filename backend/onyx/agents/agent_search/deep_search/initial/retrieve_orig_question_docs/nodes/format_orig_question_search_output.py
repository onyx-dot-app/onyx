from onyx.agents.agent_search.deep_search.main.states import OrigQuestionRetrievalUpdate
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalOutput,
)
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.utils.logger import setup_logger

logger = setup_logger()


def format_orig_question_search_output(
    state: ExpandedRetrievalOutput,
) -> OrigQuestionRetrievalUpdate:
    """
    LangGraph node to format the search result for the original question into the
    proper format.
    """
    sub_question_retrieval_stats = state.expanded_retrieval_result.retrieval_stats
    if sub_question_retrieval_stats is None:
        sub_question_retrieval_stats = AgentChunkRetrievalStats()
    else:
        sub_question_retrieval_stats = sub_question_retrieval_stats

    return OrigQuestionRetrievalUpdate(
        orig_question_verified_reranked_documents=state.expanded_retrieval_result.verified_reranked_documents,
        orig_question_sub_query_retrieval_results=state.expanded_retrieval_result.expanded_query_results,
        orig_question_retrieved_documents=state.retrieved_documents,
        orig_question_retrieval_stats=sub_question_retrieval_stats,
        log_messages=[],
    )
