# create adapter from Tool to FunctionTool
import json
from typing import Any
from typing import Union

from agents import FunctionTool
from agents import RunContextWrapper

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import IterationInstructions
from onyx.chat.turn.models import ChatTurnContext
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.built_in_tools_v2 import BUILT_IN_TOOL_MAP_V2
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
    args = json.loads(json_string) if json_string else {}
    index = run_context.context.current_run_step
    run_context.context.run_dependencies.emitter.emit(
        Packet(
            ind=index,
            obj=CustomToolStart(type="custom_tool_start", tool_name=tool.name),
        )
    )
    results = []
    run_context.context.iteration_instructions.append(
        IterationInstructions(
            iteration_nr=index,
            plan=f"Running {tool.name}",
            purpose=f"Running {tool.name}",
            reasoning=f"Running {tool.name}",
        )
    )
    for result in tool.run(**args):
        results.append(result)
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
        run_context.context.aggregated_context.global_iteration_responses.append(
            IterationAnswer(
                tool=tool.name,
                tool_id=tool.id,
                iteration_nr=index,
                parallelization_nr=0,
                question=json.dumps(args) if args else "",
                reasoning=f"Running {tool.name}",
                data=data,
                file_ids=file_ids,
                cited_documents={},
                additional_data=None,
                response_type=custom_summary.response_type,
                answer=str(data) if data else str(file_ids),
            )
        )
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
    return results


def tool_to_function_tool(tool: Tool) -> FunctionTool:
    return FunctionTool(
        name=tool.name,
        description=tool.description,
        params_json_schema=tool.tool_definition()["function"]["parameters"],
        on_invoke_tool=lambda context, json_string: _tool_run_wrapper(
            context, tool, json_string
        ),
    )


def tools_to_function_tools(tools: list[Tool]) -> list[FunctionTool]:
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
