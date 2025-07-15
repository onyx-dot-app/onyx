from enum import Enum

from pydantic import BaseModel

from onyx.context.search.models import InferenceSection


class DRPath(str, Enum):
    SEARCH = "SEARCH"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    CLOSER = "CLOSER"


class OrchestratorStep(BaseModel):
    tool: DRPath
    questions: list[str]


class OrchestratorDecisonsNoPlan(BaseModel):
    reasoning: str
    next_step: OrchestratorStep


class OrchestrationPlan(BaseModel):
    reasoning: str
    plan: str


class SearchAnswer(BaseModel):
    reasoning: str
    answer: str
    citations: str


class IterationAnswer(BaseModel):
    iteration_nr: int
    parallelization_nr: int
    question: str
    answer: str
    cited_documents: list[InferenceSection]


class AggregatedDRContext(BaseModel):
    context: str
    cited_documents: list[InferenceSection]
