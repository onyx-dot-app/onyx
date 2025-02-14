from langchain_core.messages import AIMessageChunk
from langchain_core.messages import ToolCall

from onyx.agents.agent_search.orchestration.states import ToolChoice
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_tool_choice_update(
    tool_message: AIMessageChunk, tools: list[Tool]
) -> ToolChoiceUpdate:
    # If no tool calls are emitted by the LLM, we should not choose a tool
    if len(tool_message.tool_calls) == 0:
        logger.debug("No tool calls emitted by LLM")
        return ToolChoiceUpdate(
            tool_choices=[None],
        )

    # TODO: here we could handle parallel tool calls. Right now
    # we just pick the first one that matches.
    selected_tool: Tool | None = None
    selected_tool_call_request: ToolCall | None = None
    for tool_call_request in tool_message.tool_calls:
        known_tools_by_name = [
            tool for tool in tools if tool.name == tool_call_request["name"]
        ]

        if known_tools_by_name:
            selected_tool = known_tools_by_name[0]
            selected_tool_call_request = tool_call_request
            break

        logger.error(
            "Tool call requested with unknown name field. \n"
            f"tools: {tools}"
            f"tool_call_request: {tool_call_request}"
        )

    if not selected_tool or not selected_tool_call_request:
        raise ValueError(
            f"Tool call attempted with tool {selected_tool}, request {selected_tool_call_request}"
        )

    logger.debug(f"Selected tool: {selected_tool.name}")
    logger.debug(f"Selected tool call request: {selected_tool_call_request}")

    return ToolChoiceUpdate(
        tool_choices=[
            ToolChoice(
                tool=selected_tool,
                tool_args=selected_tool_call_request["args"],
                id=selected_tool_call_request["id"],
            )
        ],
    )
