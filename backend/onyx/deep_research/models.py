from pydantic import BaseModel, Field

from onyx.chat.citation_processor import CitationMapping
from onyx.llm.models import Message
from onyx.server.query_and_chat.placement import Placement


class ResearchAgentCallResult(BaseModel):
    intermediate_report: str
    citation_mapping: CitationMapping
    output_messages: list[Message] = Field(default_factory=list)
    call_placements: dict[str, Placement] = Field(default_factory=dict)


class CombinedResearchAgentCallResult(BaseModel):
    # The None is needed here to keep the mappings consistent
    # we later skip the failed research results but we need to know
    # which ones failed
    intermediate_reports: list[str | None]
    citation_mapping: CitationMapping
