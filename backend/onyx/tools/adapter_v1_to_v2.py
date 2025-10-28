# create adapter from Tool to FunctionTool
import json
from collections.abc import Sequence
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
from onyx.tools.force import ForceUseTool
from onyx.tools.tool import Tool
from onyx.tools.tool_implementations.agent.agent_tool import AgentTool
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.tools.tool_implementations_v2.agent_tool import call_agent
from onyx.tools.tool_implementations_v2.tool_accounting import tool_accounting

# Type alias for tools that need custom handling
CustomOrMcpOrAgentTool = Union[CustomTool, MCPTool, AgentTool]


def is_custom_or_mcp_or_agent_tool(tool: Tool) -> bool:
    """Check if a tool is a CustomTool, MCPTool, or AgentTool."""
    return isinstance(tool, (CustomTool, MCPTool, AgentTool))


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


def custom_or_mcp_tool_to_function_tool(tool: Tool) -> FunctionTool:
    return FunctionTool(
        name=tool.name,
        description=tool.description,
        params_json_schema=tool.tool_definition()["function"]["parameters"],
        on_invoke_tool=lambda context, json_string: _tool_run_wrapper(
            context, tool, json_string
        ),
    )


def agent_tool_to_function_tool(agent_tool: AgentTool) -> FunctionTool:
    """Convert an AgentTool to a FunctionTool that calls call_agent."""

    # Create a wrapper that calls call_agent with the bound persona ID
    async def invoke_agent(
        context: RunContextWrapper[ChatTurnContext], json_string: str
    ) -> str:
        # Parse the query from the JSON string
        args = json.loads(json_string)
        query = args.get("query", "")

        # Call the call_agent function with the target persona ID
        return call_agent(
            run_context=context,
            query=query,
            agent_persona_id=agent_tool.target_persona_id,
        )

    return FunctionTool(
        name=agent_tool.name,
        description=agent_tool.description,
        params_json_schema=agent_tool.tool_definition()["function"]["parameters"],
        on_invoke_tool=invoke_agent,
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
        if isinstance(tool, (CustomTool, MCPTool))
    ]
    agent_tools: list[FunctionTool] = [
        agent_tool_to_function_tool(tool)  # type: ignore
        for tool in tools
        if isinstance(tool, AgentTool)
    ]

    return flattened_builtin_tools + custom_and_mcp_tools + agent_tools


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
