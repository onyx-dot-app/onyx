from pydantic import BaseModel


class RefinementSubQuestion(BaseModel):
    sub_question: str
    sub_question_id: str
    verified: bool
    answered: bool
    answer: str


class AgentTimings(BaseModel):
    base_duration_s: float | None
    refined_duration_s: float | None
    full_duration_s: float | None


class AgentBaseMetrics(BaseModel):
    num_verified_documents_total: int | None
    num_verified_documents_core: int | None
    verified_avg_score_core: float | None
    num_verified_documents_base: int | float | None
    verified_avg_score_base: float | None = None
    base_doc_boost_factor: float | None = None
    support_boost_factor: float | None = None
    duration_s: float | None = None


class AgentRefinedMetrics(BaseModel):
    refined_doc_boost_factor: float | None = None
    refined_question_boost_factor: float | None = None
    duration_s: float | None = None


class AgentAdditionalMetrics(BaseModel):
    pass
