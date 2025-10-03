# create adapter from Tool to FunctionTool
import json
from typing import Union

from agents import FunctionTool
from agents import RunContextWrapper

from onyx.chat.turn.models import ChatTurnContext
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP_V2
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool

# Type alias for tools that need custom handling
CustomOrMcpTool = Union[CustomTool, MCPTool]


def is_custom_or_mcp_tool(tool: Tool) -> bool:
    """Check if a tool is a CustomTool or MCPTool."""
    return isinstance(tool, CustomTool) or isinstance(tool, MCPTool)


async def _tool_run_wrapper(
    tool: Tool, run_context: RunContextWrapper[ChatTurnContext], json_string: str
):
    """
    Wrapper function to adapt Tool.run() to FunctionTool.on_invoke_tool() signature.
    """
    args = json.loads(json_string) if json_string else {}
    index = run_context.context.current_run_step + 1
    if is_custom_or_mcp_tool(tool):
        run_context.context.run_dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=CustomToolStart(type="custom_tool_start", tool_name=tool.name),
            )
        )
    results = []
    for result in tool.run(**args):
        results.append(result)
    if is_custom_or_mcp_tool(tool):
        # Extract data from CustomToolCallSummary within the ToolResponse
        custom_summary = result.response
        data = None
        file_ids = None

        # Handle different response types
        if custom_summary.response_type in ["image", "csv"] and hasattr(
            custom_summary.tool_result, "file_ids"
        ):
            file_ids = custom_summary.tool_result.file_ids
        else:
            data = custom_summary.tool_result

        run_context.context.run_dependencies.emitter.emit(
            Packet(
                ind=index,
                obj=CustomToolDelta(
                    type="custom_tool_delta",
                    tool_name=tool.name,
                    response_type=custom_summary.response_type,
                    data=data,
                    file_ids=file_ids,
                ),
            )
        )
        run_context.context.run_dependencies.emitter.emit(
            Packet(ind=index, obj=SectionEnd(type="section_end"))
        )
    run_context.context.current_run_step = index + 1
    return results


def tool_to_function_tool(tool: Tool) -> FunctionTool:
    return FunctionTool(
        name=tool.name,
        description=tool.description,
        params_json_schema=tool.tool_definition()["function"]["parameters"],
        on_invoke_tool=lambda context, json_string: _tool_run_wrapper(
            tool, context, json_string
        ),
    )


def tools_to_function_tools(tools: list[Tool]) -> list[FunctionTool]:
    pass

    onyx_tools: list[list[FunctionTool]] = [
        BUILT_IN_TOOL_MAP_V2[type(tool).__name__]
        for tool in tools
        if type(tool).__name__ in BUILT_IN_TOOL_MAP_V2
    ]
    flattened_builtin_tools: list[FunctionTool] = [
        onyx_tool for sublist in onyx_tools for onyx_tool in sublist
    ]
    custom_and_mcp_tools: list[FunctionTool] = [
        tool_to_function_tool(tool) for tool in tools if is_custom_or_mcp_tool(tool)
    ]

    return flattened_builtin_tools + custom_and_mcp_tools
