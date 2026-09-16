from enum import Enum

from pydantic import BaseModel, Field

from onyx.chat.citation_processor import CitationMapping


class ResearchAgentCallResult(BaseModel):
    intermediate_report: str
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
    sources: CitationMapping = Field(default_factory=dict)
    elapsed_seconds: float = 0
