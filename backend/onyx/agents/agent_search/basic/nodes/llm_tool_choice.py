from typing import cast
from uuid import uuid4

from langchain_core.messages import ToolCall
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.basic.states import BasicState
from onyx.agents.agent_search.basic.states import ToolChoice
from onyx.agents.agent_search.basic.states import ToolChoiceUpdate
from onyx.agents.agent_search.basic.utils import process_llm_stream
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.chat.tool_handling.tool_response_handler import get_tool_by_name
from onyx.chat.tool_handling.tool_response_handler import (
    get_tool_call_for_non_tool_calling_llm_impl,
)
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


# TODO: break this out into an implementation function
# and a function that handles extracting the necessary fields
# from the state and config
# TODO: fan-out to multiple tool call nodes? Make this configurable?
def llm_tool_choice(state: BasicState, config: RunnableConfig) -> ToolChoiceUpdate:
    """
    This node is responsible for calling the LLM to choose a tool. If no tool is chosen,
    The node MAY emit an answer, depending on whether state["should_stream_answer"] is set.
    """
    should_stream_answer = state["should_stream_answer"]

    agent_config = cast(AgentSearchConfig, config["metadata"]["config"])
    using_tool_calling_llm = agent_config.using_tool_calling_llm
    prompt_builder = agent_config.prompt_builder
    llm = agent_config.primary_llm
    skip_gen_ai_answer_generation = agent_config.skip_gen_ai_answer_generation

    structured_response_format = agent_config.structured_response_format
    tools = agent_config.tools or []
    force_use_tool = agent_config.force_use_tool

    tool, tool_args = None, None
    if force_use_tool.force_use and force_use_tool.args is not None:
        tool_name, tool_args = (
            force_use_tool.tool_name,
            force_use_tool.args,
        )
        tool = get_tool_by_name(tools, tool_name)

    # special pre-logic for non-tool calling LLM case
    elif not using_tool_calling_llm and tools:
        chosen_tool_and_args = get_tool_call_for_non_tool_calling_llm_impl(
            force_use_tool=force_use_tool,
            tools=tools,
            prompt_builder=prompt_builder,
            llm=llm,
        )
        if chosen_tool_and_args:
            tool, tool_args = chosen_tool_and_args

    # If we have a tool and tool args, we are redy to request a tool call.
    # This only happens if the tool call was forced or we are using a non-tool calling LLM.
    if tool and tool_args:
        return ToolChoiceUpdate(
            tool_choice=ToolChoice(
                tool=tool,
                tool_args=tool_args,
                id=str(uuid4()),
            ),
        )

    # if we're skipping gen ai answer generation, we should only
    # continue if we're forcing a tool call (which will be emitted by
    # the tool calling llm in the stream() below)
    if skip_gen_ai_answer_generation and not force_use_tool.force_use:
        return ToolChoiceUpdate(
            tool_choice=None,
        )

    # At this point, we are either using a tool calling LLM or we are skipping the tool call.
    # DEBUG: good breakpoint
    stream = llm.stream(
        # For tool calling LLMs, we want to insert the task prompt as part of this flow, this is because the LLM
        # may choose to not call any tools and just generate the answer, in which case the task prompt is needed.
        prompt=prompt_builder.build(),
        tools=[tool.tool_definition() for tool in tools] or None,
        tool_choice=("required" if tools and force_use_tool.force_use else None),
        structured_response_format=structured_response_format,
    )

    tool_message = process_llm_stream(stream, should_stream_answer)

    # If no tool calls are emitted by the LLM, we should not choose a tool
    if len(tool_message.tool_calls) == 0:
        return ToolChoiceUpdate(
            tool_choice=None,
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

    logger.info(f"Selected tool: {selected_tool.name}")
    logger.debug(f"Selected tool call request: {selected_tool_call_request}")

    return ToolChoiceUpdate(
        tool_choice=ToolChoice(
            tool=selected_tool,
            tool_args=selected_tool_call_request["args"],
            id=selected_tool_call_request["id"],
        ),
    )
