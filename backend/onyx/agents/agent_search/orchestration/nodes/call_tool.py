from typing import cast

from langchain_core.messages import AIMessageChunk
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables.config import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.orchestration.states import ToolCallOutput
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AnswerPacket
from onyx.tools.message import build_tool_message
from onyx.tools.message import ToolCallSummary
from onyx.tools.tool_runner import ToolRunner
from onyx.utils.logger import setup_logger


logger = setup_logger()


class ToolCallException(Exception):
    """Exception raised for errors during tool calls."""


def emit_packet(packet: AnswerPacket, writer: StreamWriter) -> None:
    write_custom_event("basic_response", packet, writer)


def call_tool(
    state: ToolChoiceUpdate,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> ToolCallUpdate:
    """Calls the tool specified in the state and updates the state with the result"""

    cast(GraphConfig, config["metadata"]["config"])

    tool_choice = state.tool_choice
    if tool_choice is None:
        raise ValueError("Cannot invoke tool call node without a tool choice")

    tool = tool_choice.tool
    tool_args = tool_choice.tool_args
    tool_id = tool_choice.id
    tool_runner = ToolRunner(tool, tool_args)
    tool_kickoff = tool_runner.kickoff()

    emit_packet(tool_kickoff, writer)

    try:
        tool_responses = []
        for response in tool_runner.tool_responses():
            tool_responses.append(response)
            emit_packet(response, writer)

        tool_final_result = tool_runner.tool_final_result()
        emit_packet(tool_final_result, writer)
    except Exception as e:
        raise ToolCallException(
            f"Error during tool call for {tool.display_name}: {e}"
        ) from e

    tool_call = ToolCall(name=tool.name, args=tool_args, id=tool_id)
    tool_call_summary = ToolCallSummary(
        tool_call_request=AIMessageChunk(content="", tool_calls=[tool_call]),
        tool_call_result=build_tool_message(
            tool_call, tool_runner.tool_message_content()
        ),
    )

    tool_call_output = ToolCallOutput(
        tool_call_summary=tool_call_summary,
        tool_call_kickoff=tool_kickoff,
        tool_call_responses=tool_responses,
        tool_call_final_result=tool_final_result,
    )
    return ToolCallUpdate(tool_call_output=tool_call_output)
