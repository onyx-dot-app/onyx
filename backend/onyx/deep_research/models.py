from pydantic import BaseModel

from onyx.context.search.models import SearchDoc
from onyx.tools.models import ToolCallKickoff


class SpecialToolCalls(BaseModel):
    think_tool_call: ToolCallKickoff | None = None
    generate_report_tool_call: ToolCallKickoff | None = None


class ResearchAgentCallResult(BaseModel):
    intermediate_report: str
    search_docs: list[SearchDoc]
