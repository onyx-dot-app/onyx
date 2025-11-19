from enum import Enum

from pydantic import BaseModel

from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.sub_agents.image_generation.models import (
    GeneratedImage,
)
from onyx.context.search.models import InferenceSection
from onyx.tools.tool import Tool


class OrchestratorStep(BaseModel):
    tool: str
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


class DecisionResponse(BaseModel):
    reasoning: str
    decision: str


class QueryEvaluationResponse(BaseModel):
    reasoning: str
    query_permitted: bool


class OrchestrationClarificationInfo(BaseModel):
    clarification_question: str
    clarification_response: str | None = None


class WebSearchAnswer(BaseModel):
    urls_to_open_indices: list[int]


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
    llm_path: str  # the path for the LLM to refer by
    path: DRPath  # the actual path in the graph
    description: str
    metadata: dict[str, str]
    cost: float
    tool_object: Tool | None = None  # None for CLOSER

    class Config:
        arbitrary_types_allowed = True


class IterationInstructions(BaseModel):
    iteration_nr: int
    plan: str | None
    reasoning: str
    purpose: str


class IterationAnswer(BaseModel):
    tool: str
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
    response_type: str | None = None
    data: dict | list | str | int | float | bool | None = None
    file_ids: list[str] | None = None
    # TODO: This is not ideal, but we'll can rework the schema
    # for deep research later
    is_web_fetch: bool = False
    # for image generation step-types
    generated_images: list[GeneratedImage] | None = None
    # for multi-query search tools (v2 web search and internal search)
    # TODO: Clean this up to be more flexible to tools
    queries: list[str] | None = None


class AggregatedDRContext(BaseModel):
    context: str
    cited_documents: list[InferenceSection]
    is_internet_marker_dict: dict[str, bool]
    global_iteration_responses: list[IterationAnswer]


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
