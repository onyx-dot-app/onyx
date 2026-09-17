from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from onyx.context.search.models import SearchDoc


class ResearchAgentCallResult(BaseModel):
    type: Literal["research_result"] = "research_result"
    intermediate_report: str
    citation_mapping: dict[int, SearchDoc]


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
