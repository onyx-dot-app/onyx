from pydantic import BaseModel

from onyx.tools.models import ToolCallKickoff


class SpecialToolCalls(BaseModel):
    think_tool_call: ToolCallKickoff | None = None
    generate_report_tool_call: ToolCallKickoff | None = None
