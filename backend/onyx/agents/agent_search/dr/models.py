from enum import Enum

from pydantic import BaseModel

from onyx.agents.agent_search.dr.enums import DRPath
from onyx.context.search.models import InferenceSection


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


class QueryEvaluationResponse(BaseModel):
    reasoning: str
    query_permitted: bool


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
    tool_id: int
    name: str
    display_name: str
    description: str
    path: DRPath
    metadata: dict[str, str]
    cost: float


class IterationInstructions(BaseModel):
    iteration_nr: int
    plan: str | None
    reasoning: str
    purpose: str


class GenericToolAnswer(BaseModel):
    reasoning: str
    answer: str
    background_info: str


class IterationAnswer(BaseModel):
    tool: DRPath
    tool_id: int
    iteration_nr: int
    parallelization_nr: int
    question: str
    reasoning: str | None
    answer: str
    cited_documents: dict[int, InferenceSection]
    background_info: str | None = None
    claims: list[str] | None = None
    additional_data: dict[str, str] | None = None


class AggregatedDRContext(BaseModel):
    context: str
    cited_documents: list[InferenceSection]
    global_iteration_responses: list[IterationAnswer]


class ResearchType(str, Enum):
    """Time budget options for agent search operations"""

    FAST = "fast"
    SHALLOW = "shallow"
    DEEP = "deep"


class DRPromptPurpose(str, Enum):
    PLAN = "PLAN"
    NEXT_STEP = "NEXT_STEP"
    NEXT_STEP_REASONING = "NEXT_STEP_REASONING"
    NEXT_STEP_PURPOSE = "NEXT_STEP_PURPOSE"
    CLARIFICATION = "CLARIFICATION"


class BaseSearchProcessingResponse(BaseModel):
    specified_source_types: list[str]
    rewritten_query: str
    time_filter: str
