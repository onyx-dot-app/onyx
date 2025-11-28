# create adapter from Tool to FunctionTool
from collections.abc import Sequence
from typing import Any
from typing import Union

from agents import FunctionTool
from agents import RunContextWrapper

from onyx.chat.turn.models import ChatTurnContext
from onyx.tools.built_in_tools_v2 import BUILT_IN_TOOL_MAP_V2
from onyx.tools.force import ForceUseTool
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting

# Type alias for tools that need custom handling
CustomOrMcpTool = Union[CustomTool, MCPTool]


def is_custom_or_mcp_tool(tool: Tool) -> bool:
    """Check if a tool is a CustomTool or MCPTool."""
    return isinstance(tool, CustomTool) or isinstance(tool, MCPTool)


@tool_accounting
async def _tool_run_wrapper(
    run_context: RunContextWrapper[ChatTurnContext], tool: Tool, json_string: str
) -> list[Any]:
    """
    Wrapper function to adapt Tool.run() to FunctionTool.on_invoke_tool() signature.
    """
    # args = json.loads(json_string) if json_string else {}
    # index = run_context.context.current_run_step
    # run_context.context.run_dependencies.emitter.emit(
    #     Packet(
    #         ind=index,
    #         obj=CustomToolStart(type="custom_tool_start", tool_name=tool.name),
    #     )
    # )
    # results = []
    # for result in tool.run(**args):
    #     results.append(result)
    #     # Extract data from CustomToolCallSummary within the ToolResponse
    #     custom_summary = result.response
    #     data = None
    #     file_ids = None

    #     # Handle different response types
    #     if custom_summary.response_type in ["image", "csv"] and hasattr(
    #         custom_summary.tool_result, "file_ids"
    #     ):
    #         file_ids = custom_summary.tool_result.file_ids
    #     else:
    #         data = custom_summary.tool_result
    #     run_context.context.run_dependencies.emitter.emit(
    #         Packet(
    #             ind=index,
    #             obj=CustomToolDelta(
    #                 type="custom_tool_delta",
    #                 tool_name=tool.name,
    #                 response_type=custom_summary.response_type,
    #                 data=data,
    #                 file_ids=file_ids,
    #             ),
    #         )
    #     )
    return []


def custom_or_mcp_tool_to_function_tool(tool: Tool) -> FunctionTool:
    # TODO: this logic is basically a hack to set strict_json_schema to False.
    # Ideally we'd like to actually respect the True/False present in additionalProperties.
    # However, we've seen some cases of a tool asking for strict json but not actually requiring it.
    # This deserves a larger QA effort with a bunch of different MCP tools
    tool_params = tool.tool_definition()["function"]["parameters"]
    strict_json_schema = "additionalProperties" not in tool_params
    return FunctionTool(
        name=tool.name,
        description=tool.description,
        params_json_schema=tool_params,
        strict_json_schema=strict_json_schema,
        on_invoke_tool=lambda context, json_string: _tool_run_wrapper(
            context, tool, json_string
        ),
    )


def tools_to_function_tools(tools: Sequence[Tool]) -> Sequence[FunctionTool]:
    onyx_tools: Sequence[Sequence[FunctionTool]] = [
        BUILT_IN_TOOL_MAP_V2[type(tool).__name__]
        for tool in tools
        if type(tool).__name__ in BUILT_IN_TOOL_MAP_V2
    ]
    flattened_builtin_tools: list[FunctionTool] = [
        onyx_tool for sublist in onyx_tools for onyx_tool in sublist
    ]
    custom_and_mcp_tools: list[FunctionTool] = [
        custom_or_mcp_tool_to_function_tool(tool)
        for tool in tools
        if is_custom_or_mcp_tool(tool)
    ]

    return flattened_builtin_tools + custom_and_mcp_tools


def force_use_tool_to_function_tool_names(
    force_use_tool: ForceUseTool, tools: Sequence[Tool]
) -> str | None:
    if not force_use_tool.force_use:
        return None

    # Filter tools to only those matching the force_use_tool name
    filtered_tools = [tool for tool in tools if tool.name == force_use_tool.tool_name]

    # Convert to function tools
    function_tools = tools_to_function_tools(filtered_tools)

    # Return the first name if available, otherwise None
    return function_tools[0].name if function_tools else None
