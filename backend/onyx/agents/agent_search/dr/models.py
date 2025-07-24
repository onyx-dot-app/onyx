from enum import Enum

from pydantic import BaseModel

from onyx.context.search.models import InferenceSection


class DRPath(str, Enum):
    CLARIFIER = "CLARIFIER"
    ORCHESTRATOR = "ORCHESTRATOR"
    SEARCH = "SEARCH"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    INTERNET_SEARCH = "INTERNET_SEARCH"
    CLOSER = "CLOSER"
    END = "END"


class OrchestratorStep(BaseModel):
    tool: DRPath
    questions: list[str]


class OrchestratorDecisonsNoPlan(BaseModel):
    reasoning: str
    next_step: OrchestratorStep


class OrchestrationPlan(BaseModel):
    reasoning: str
    plan: str


class OrchestrationFeedbackRequest(BaseModel):
    feedback_needed: bool = False
    feedback_addressed: bool | None = None
    feedback_request: str | None = None
    feedback_answer: str | None = None


class SearchAnswer(BaseModel):
    reasoning: str
    answer: str
    citations: str


class IterationAnswer(BaseModel):
    tool: DRPath
    iteration_nr: int
    parallelization_nr: int
    question: str
    answer: str
    cited_documents: list[InferenceSection]


class AggregatedDRContext(BaseModel):
    context: str
    cited_documents: list[InferenceSection]


class DRTimeBudget(str, Enum):
    """Time budget options for agent search operations"""

    FAST = "fast"
    SHALLOW = "shallow"
    DEEP = "deep"
