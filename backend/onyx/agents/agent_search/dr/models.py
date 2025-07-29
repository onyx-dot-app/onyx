from enum import Enum

from pydantic import BaseModel

from onyx.context.search.models import InferenceSection


class DRPath(str, Enum):
    CLARIFIER = "CLARIFIER"
    ORCHESTRATOR = "ORCHESTRATOR"
    SEARCH = "SEARCH"
    GENERIC_TOOL = "GENERIC_TOOL"
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


class ClarificationGenerationResponse(BaseModel):
    clarification_needed: bool
    clarification_question: str


class OrchestrationClarificationInfo(BaseModel):
    clarification_question: str
    clarification_response: str | None = None


class SearchAnswer(BaseModel):
    reasoning: str
    answer: str
    claims: list[str] | None = None


class TestInfoCompleteResponse(BaseModel):
    reasoning: str
    complete: bool
    gaps: list[str]


# TODO: revisit with custom tools implementation in v2
# each tool should be a class with the attributes below, plus the actual tool implementation
# this will also allow custom tools to have their own cost
class OrchestratorTool(BaseModel):
    name: str
    display_name: str
    description: str
    path: DRPath
    metadata: dict[str, str]
    cost: float


class GenericToolAnswer(BaseModel):
    reasoning: str
    answer: str
    background_info: str


class IterationAnswer(BaseModel):
    tool: DRPath
    iteration_nr: int
    parallelization_nr: int
    question: str
    answer: str
    cited_documents: dict[int, InferenceSection]
    background_info: str | None = None
    claims: list[str] | None = None


class AggregatedDRContext(BaseModel):
    context: str
    cited_documents: list[InferenceSection]


class DRTimeBudget(str, Enum):
    """Time budget options for agent search operations"""

    FAST = "fast"
    SHALLOW = "shallow"
    DEEP = "deep"


class DRPromptPurpose(str, Enum):
    PLAN = "PLAN"
    NEXT_STEP = "NEXT_STEP"
    CLARIFICATION = "CLARIFICATION"
