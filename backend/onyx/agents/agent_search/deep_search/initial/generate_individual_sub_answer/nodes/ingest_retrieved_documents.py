from onyx.agents.agent_search.deep_search.initial.generate_individual_sub_answer.states import (
    SubQuestionRetrievalIngestionUpdate,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalOutput,
)
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats


def ingest_retrieved_documents(
    state: ExpandedRetrievalOutput,
) -> SubQuestionRetrievalIngestionUpdate:
    """
    LangGraph node to ingest the retrieved documents to format it for the sub-answer.
    """
    sub_question_retrieval_stats = state.expanded_retrieval_result.retrieval_stats
    if sub_question_retrieval_stats is None:
        sub_question_retrieval_stats = [AgentChunkRetrievalStats()]

    return SubQuestionRetrievalIngestionUpdate(
        expanded_retrieval_results=state.expanded_retrieval_result.expanded_query_results,
        verified_reranked_documents=state.expanded_retrieval_result.verified_reranked_documents,
        context_documents=state.expanded_retrieval_result.context_documents,
        sub_question_retrieval_stats=sub_question_retrieval_stats,
    )
