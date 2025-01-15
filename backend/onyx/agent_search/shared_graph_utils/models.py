from typing import Literal

from pydantic import BaseModel


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
    verified_count: int | None
    verified_avg_scores: float | None
    rejected_count: int | None
    rejected_avg_scores: float | None
    verified_doc_chunk_ids: list[str]
    dismissed_doc_chunk_ids: list[str]


class InitialAgentResultStats(BaseModel):
    sub_questions: dict[str, float | int | None]
    original_question: dict[str, float | int | None]
    agent_effectiveness: dict[str, float | int | None]


class RefinedAgentStats(BaseModel):
    revision_doc_efficiency: float | None
    revision_question_efficiency: float | None
