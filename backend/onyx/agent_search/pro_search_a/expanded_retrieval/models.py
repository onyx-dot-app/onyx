from pydantic import BaseModel

from onyx.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agent_search.shared_graph_utils.models import RetrievalFitStats
from onyx.context.search.models import InferenceSection
from onyx.tools.models import SearchQueryInfo

### Models ###


class QueryResult(BaseModel):
    query: str
    search_results: list[InferenceSection]
    stats: RetrievalFitStats | None
    query_info: SearchQueryInfo | None


class ExpandedRetrievalResult(BaseModel):
    expanded_queries_results: list[QueryResult]
    all_documents: list[InferenceSection]
    sub_question_retrieval_stats: AgentChunkStats
