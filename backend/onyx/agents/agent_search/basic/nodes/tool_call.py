from typing import cast

from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import AIMessageChunk
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.basic.states import BasicState
from onyx.agents.agent_search.basic.states import ToolCallUpdate
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.chat.models import AnswerPacket
from onyx.tools.message import build_tool_message
from onyx.tools.message import ToolCallSummary
from onyx.tools.tool_runner import ToolRunner
from onyx.utils.logger import setup_logger


logger = setup_logger()


def emit_packet(packet: AnswerPacket) -> None:
    dispatch_custom_event("basic_response", packet)


# TODO: handle is_cancelled
def tool_call(state: BasicState, config: RunnableConfig) -> ToolCallUpdate:
    """Calls the tool specified in the state and updates the state with the result"""
    # TODO: implement

    cast(AgentSearchConfig, config["metadata"]["config"])
    # Unnecessary now, node should only be called if there is a tool call
    # if not self.tool_call_chunk or not self.tool_call_chunk.tool_calls:
    #     return

    tool_choice = state["tool_choice"]
    if tool_choice is None:
        raise ValueError("Cannot invoke tool call node without a tool choice")

    tool = tool_choice["tool"]
    tool_args = tool_choice["tool_args"]
    tool_id = tool_choice["id"]
    tool_runner = ToolRunner(tool, tool_args)
    tool_kickoff = tool_runner.kickoff()

    # TODO: custom events for yields
    emit_packet(tool_kickoff)

    tool_responses = []
    for response in tool_runner.tool_responses():
        tool_responses.append(response)
        emit_packet(response)

    tool_final_result = tool_runner.tool_final_result()
    emit_packet(tool_final_result)

    tool_call = ToolCall(name=tool.name, args=tool_args, id=tool_id)
    tool_call_summary = ToolCallSummary(
        tool_call_request=AIMessageChunk(content="", tool_calls=[tool_call]),
        tool_call_result=build_tool_message(
            tool_call, tool_runner.tool_message_content()
        ),
    )

    return ToolCallUpdate(
        tool_call_summary=tool_call_summary,
        tool_call_kickoff=tool_kickoff,
        tool_call_responses=tool_responses,
        tool_call_final_result=tool_final_result,
    )
