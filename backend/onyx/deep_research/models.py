from pydantic import BaseModel

from onyx.chat.citation_processor import CitationMapping
from onyx.tools.models import ToolCallKickoff


class SpecialToolCalls(BaseModel):
    think_tool_call: ToolCallKickoff | None = None
    generate_report_tool_call: ToolCallKickoff | None = None


class ResearchAgentCallResult(BaseModel):
    intermediate_report: str
    citation_mapping: CitationMapping


class CombinedResearchAgentCallResult(BaseModel):
    # The None is needed here to keep the mappings consistent
    # we later skip the failed research results but we need to know
    # which ones failed
    intermediate_reports: list[str | None]
    citation_mapping: CitationMapping
