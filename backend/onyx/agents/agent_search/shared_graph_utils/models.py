from typing import Literal

from pydantic import BaseModel

from onyx.agents.agent_search.deep_search_a.main.models import AgentAdditionalMetrics
from onyx.agents.agent_search.deep_search_a.main.models import AgentBaseMetrics
from onyx.agents.agent_search.deep_search_a.main.models import AgentRefinedMetrics
from onyx.agents.agent_search.deep_search_a.main.models import AgentTimings
from onyx.context.search.models import InferenceSection
from onyx.tools.models import SearchQueryInfo


# Pydantic models for structured outputs
class RewrittenQueries(BaseModel):
    rewritten_queries: list[str]


class BinaryDecision(BaseModel):
    decision: Literal["yes", "no"]


class BinaryDecisionWithReasoning(BaseModel):
    reasoning: str
    decision: Literal["yes", "no"]


class RetrievalFitScoreMetrics(BaseModel):
    scores: dict[str, float]
    chunk_ids: list[str]


class RetrievalFitStats(BaseModel):
    fit_score_lift: float
    rerank_effect: float
    fit_scores: dict[str, RetrievalFitScoreMetrics]


class AgentChunkScores(BaseModel):
    scores: dict[str, dict[str, list[int | float]]]


class AgentChunkStats(BaseModel):
    verified_count: int | None = None
    verified_avg_scores: float | None = None
    rejected_count: int | None = None
    rejected_avg_scores: float | None = None
    verified_doc_chunk_ids: list[str] = []
    dismissed_doc_chunk_ids: list[str] = []


class InitialAgentResultStats(BaseModel):
    sub_questions: dict[str, float | int | None]
    original_question: dict[str, float | int | None]
    agent_effectiveness: dict[str, float | int | None]


class RefinedAgentStats(BaseModel):
    revision_doc_efficiency: float | None
    revision_question_efficiency: float | None


class Term(BaseModel):
    term_name: str = ""
    term_type: str = ""
    term_similar_to: list[str] = []


### Models ###


class Entity(BaseModel):
    entity_name: str = ""
    entity_type: str = ""


class Relationship(BaseModel):
    relationship_name: str = ""
    relationship_type: str = ""
    relationship_entities: list[str] = []


class EntityRelationshipTermExtraction(BaseModel):
    entities: list[Entity] = []
    relationships: list[Relationship] = []
    terms: list[Term] = []


### Models ###


class QueryResult(BaseModel):
    query: str
    search_results: list[InferenceSection]
    stats: RetrievalFitStats | None
    query_info: SearchQueryInfo | None


class QuestionAnswerResults(BaseModel):
    question: str
    question_id: str
    answer: str
    quality: str
    expanded_retrieval_results: list[QueryResult]
    documents: list[InferenceSection]
    context_documents: list[InferenceSection]
    sub_question_retrieval_stats: AgentChunkStats


class CombinedAgentMetrics(BaseModel):
    timings: AgentTimings
    base_metrics: AgentBaseMetrics | None
    refined_metrics: AgentRefinedMetrics
    additional_metrics: AgentAdditionalMetrics
