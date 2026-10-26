from enum import Enum

from pydantic import BaseModel, Field

from onyx.chat.citation_processor import CitationMapping
from onyx.context.search.models import SearchDoc
from onyx.tools.models import ToolCallKickoff


class SpecialToolCalls(BaseModel):
    think_tool_call: ToolCallKickoff | None = None
    generate_report_tool_call: ToolCallKickoff | None = None


class ResearchAgentCallFailure(BaseModel):
    # LLM-facing explanation sent back as the failed call's tool response
    message: str


class CombinedResearchAgentCallResult(BaseModel):
    # One entry per research agent call, in call order
    intermediate_reports: list[str | ResearchAgentCallFailure]
    citation_mapping: CitationMapping


class ResearchPhase(str, Enum):
    CLARIFICATION = "clarification"
    PLANNING = "planning"
    RESEARCH = "research"
    REPORT = "report"


class ResearchMessageMetadata(BaseModel):
    """Research phase and source references attached to a generated message."""

    phase: ResearchPhase
    is_intermediate: bool = False
    is_reasoning_model: bool
    sources: dict[int, SearchDoc] = Field(default_factory=dict)
    elapsed_seconds: float = 0
