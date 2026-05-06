from onyx.coding_agent.mock_tools import GENERATE_ANSWER_TOOL_NAME
from onyx.coding_agent.models import CodingAgentSpecialToolCalls
from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.tools.models import ToolCallKickoff


def check_special_tool_calls(
    tool_calls: list[ToolCallKickoff],
) -> CodingAgentSpecialToolCalls:
    think_tool_call: ToolCallKickoff | None = None
    generate_answer_tool_call: ToolCallKickoff | None = None

    for tool_call in tool_calls:
        if tool_call.tool_name == THINK_TOOL_NAME:
            think_tool_call = tool_call
        elif tool_call.tool_name == GENERATE_ANSWER_TOOL_NAME:
            generate_answer_tool_call = tool_call

    return CodingAgentSpecialToolCalls(
        think_tool_call=think_tool_call,
        generate_answer_tool_call=generate_answer_tool_call,
    )
