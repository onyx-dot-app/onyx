from pydantic import BaseModel, Field

from onyx.chat.citation_processor import CitationMapping
from onyx.llm.models import Message
from onyx.server.query_and_chat.placement import Placement


class ResearchAgentCallResult(BaseModel):
    intermediate_report: str
    citation_mapping: CitationMapping
    output_messages: list[Message] = Field(default_factory=list)
    call_placements: dict[str, Placement] = Field(default_factory=dict)


class ResearchAgentCallFailure(BaseModel):
    # LLM-facing explanation sent back as the failed call's tool response
    message: str


class CombinedResearchAgentCallResult(BaseModel):
    # One entry per research agent call, in call order
    intermediate_reports: list[str | ResearchAgentCallFailure]
    citation_mapping: CitationMapping
