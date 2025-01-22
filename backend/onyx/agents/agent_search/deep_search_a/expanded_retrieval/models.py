from pydantic import BaseModel

from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryResult
from onyx.context.search.models import InferenceSection


class ExpandedRetrievalResult(BaseModel):
    expanded_queries_results: list[QueryResult] = []
    all_documents: list[InferenceSection] = []
    sub_question_retrieval_stats: AgentChunkStats = AgentChunkStats()
