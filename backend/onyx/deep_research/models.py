from pydantic import BaseModel

from onyx.chat.citation_processor import CitationMapping
from onyx.tools.models import ToolCallKickoff


class SpecialToolCalls(BaseModel):
    think_tool_call: ToolCallKickoff | None = None
    generate_report_tool_call: ToolCallKickoff | None = None


class ResearchAgentCallResult(BaseModel):
    intermediate_report: str
    citation_mapping: CitationMapping


class ResearchAgentCallFailure(BaseModel):
    # LLM-facing explanation sent back as the failed call's tool response
    message: str


class CombinedResearchAgentCallResult(BaseModel):
    # One entry per research agent call, in call order
    intermediate_reports: list[str | ResearchAgentCallFailure]
    citation_mapping: CitationMapping
