from pydantic import BaseModel

from onyx.tools.models import ToolCallKickoff


class CodingAgentSpecialToolCalls(BaseModel):
    think_tool_call: ToolCallKickoff | None = None
    generate_answer_tool_call: ToolCallKickoff | None = None


class CodingAgentCallResult(BaseModel):
    answer: str
