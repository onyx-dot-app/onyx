from pydantic import BaseModel

from onyx.agent_search.pro_search_a.expanded_retrieval.models import QueryResult
from onyx.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.context.search.models import InferenceSection

### Models ###


class AnswerRetrievalStats(BaseModel):
    answer_retrieval_stats: dict[str, float | int]


class QuestionAnswerResults(BaseModel):
    question: str
    question_id: str
    answer: str
    quality: str
    expanded_retrieval_results: list[QueryResult]
    documents: list[InferenceSection]
    sub_question_retrieval_stats: AgentChunkStats
