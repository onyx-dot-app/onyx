from typing import Any, Callable, Optional, cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.orchestration.nodes.tool_node_utils import (
    execute_tool,
    save_tool_call_message,
    save_tool_result_message,
    update_prompt_builder_history,
)
from onyx.chat.prompt_builder.answer_prompt_builder import AnswerPromptBuilder
from onyx.chat.tool_handling.tool_response_handler import get_tool_by_name
from onyx.utils.logger import setup_logger

logger = setup_logger()


def execute_tool_node(
    state: Any,
    config: RunnableConfig,
    writer: StreamWriter,
    tool_filter_fn: Callable[[list], list],
    instructions: str,
    tool_type: str = "",
    extract_results_fn: Optional[Callable[[list], dict]] = None,
) -> dict[str, Any]:
    """
    Generic tool execution workflow that:
    1. Filters available tools based on provided filter function
    2. Forces use of the filtered tool(s)
    3. Saves tool results to database and prompt builder
    4. Optionally extracts results using provided function

    Args:
        state: Graph state
        config: Runnable config containing agent configuration
        writer: Stream writer for emitting packets
        tool_filter_fn: Function to filter tools (e.g., lambda tools: [t for t in tools if t.name == "run_search"])
        instructions: State instructions for the LLM
        tool_type: Type description for logging (e.g., "search", "edit")
        extract_results_fn: Optional function to extract specific results from tool responses

    Returns:
        Dictionary with tool execution results
    """
    agent_config = cast(GraphConfig, config.get("metadata", {}).get("config"))

    llm = agent_config.tooling.primary_llm
    tools = agent_config.tooling.tools or []
    prompt_builder = agent_config.inputs.prompt_builder
    using_tool_calling_llm = agent_config.tooling.using_tool_calling_llm
    structured_response_format = agent_config.inputs.structured_response_format

    # Filter tools using provided function
    filtered_tools = tool_filter_fn(tools)

    if not filtered_tools:
        error_msg = (
            f"No {tool_type + ' ' if tool_type else ''}tool found in available tools"
        )
        logger.error(error_msg)
        return {"tool_used": False, "error": error_msg}

    # Get persistence info for database operations
    persistence = agent_config.persistence
    if not persistence:
        raise ValueError("GraphPersistence is required for tool workflow")

    built_prompt = (
        prompt_builder.build(state_instructions=instructions)
        if isinstance(prompt_builder, AnswerPromptBuilder)
        else prompt_builder.built_prompt
    )

    # Call LLM with forced tool usage
    stream = llm.stream(
        prompt=built_prompt,
        tools=(
            [tool.tool_definition() for tool in filtered_tools]
            if using_tool_calling_llm
            else None
        ),
        tool_choice="required" if using_tool_calling_llm else None,
        structured_response_format=structured_response_format,
    )

    tool_message = process_llm_stream(
        stream, should_stream_answer=False, writer=writer, return_text_content=False
    )

    # If no tool calls (shouldn't happen with required), return error
    if not tool_message.tool_calls:
        error_msg = f"{tool_type.title() + ' ' if tool_type else ''}node failed to generate tool call"
        logger.error(error_msg)
        return {
            "tool_used": False,
            "error": f"{tool_type.title() + ' ' if tool_type else ''}tool call failed",
        }

    # Get the tool call
    tool_call_request = tool_message.tool_calls[0]
    selected_tool = get_tool_by_name(filtered_tools, tool_call_request["name"])

    if not selected_tool:
        error_msg = f"Unknown {tool_type + ' ' if tool_type else ''}tool requested: {tool_call_request['name']}"
        logger.error(error_msg)
        return {
            "tool_used": False,
            "error": f"Unknown {tool_type + ' ' if tool_type else ''}tool: {tool_call_request['name']}",
        }

    try:
        # Save tool call to database
        tool_call_db_message = save_tool_call_message(
            selected_tool.name, tool_call_request, agent_config, tool_type
        )

        # Execute tool
        tool_runner, tool_responses = execute_tool(
            selected_tool, tool_call_request, writer
        )

        # Save tool result to database
        save_tool_result_message(tool_runner, tool_call_db_message, agent_config)

        # Update prompt builder history
        update_prompt_builder_history(prompt_builder, tool_call_request, tool_runner)

        # Build base result
        result = {"tool_used": True, "tool_name": selected_tool.name}

        # Extract additional results if function provided
        if extract_results_fn:
            extracted_results = extract_results_fn(tool_responses)
            result.update(extracted_results)
        else:
            # Default: include tool responses
            result[
                f"{tool_type}_results" if tool_type else "tool_results"
            ] = tool_responses

        return result

    except Exception as e:
        error_msg = f"Error in {tool_type + ' ' if tool_type else ''}workflow: {e}"
        logger.error(error_msg)
        return {"tool_used": False, "error": str(e)}
