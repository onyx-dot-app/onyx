from onyx.agents.agent_search.deep_search_a.answer_initial_sub_question.states import (
    RetrievalIngestionUpdate,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalOutput,
)
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkStats


def ingest_retrieval(state: ExpandedRetrievalOutput) -> RetrievalIngestionUpdate:
    sub_question_retrieval_stats = (
        state.expanded_retrieval_result.sub_question_retrieval_stats
    )
    if sub_question_retrieval_stats is None:
        sub_question_retrieval_stats = [AgentChunkStats()]

    return RetrievalIngestionUpdate(
        expanded_retrieval_results=state.expanded_retrieval_result.expanded_queries_results,
        documents=state.expanded_retrieval_result.all_documents,
        sub_question_retrieval_stats=sub_question_retrieval_stats,
    )
