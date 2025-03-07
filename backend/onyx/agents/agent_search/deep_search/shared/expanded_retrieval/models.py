from pydantic import BaseModel

from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.context.search.models import InferenceSection


class QuestionRetrievalResult(BaseModel):
    expanded_query_results: list[QueryRetrievalResult] = []
    retrieved_documents: list[InferenceSection] = []
    verified_reranked_documents: list[InferenceSection] = []
    context_documents: list[InferenceSection] = []
    retrieval_stats: AgentChunkRetrievalStats = AgentChunkRetrievalStats()
