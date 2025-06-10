from langgraph.graph import END, START, StateGraph

from onyx.agents.agent_search.document_chat.states import (
    DocumentChatInput,
    DocumentChatOutput,
    DocumentChatState,
)
from onyx.agents.agent_search.orchestration.nodes.call_tool import call_tool
from onyx.agents.agent_search.orchestration.nodes.choose_tool import choose_tool
from onyx.agents.agent_search.orchestration.nodes.prepare_tool_input import (
    prepare_tool_input,
)
from onyx.agents.agent_search.orchestration.nodes.use_tool_response import (
    basic_use_tool_response,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def document_chat_graph_builder() -> StateGraph:
    graph = StateGraph(
        state_schema=DocumentChatState,
        input=DocumentChatInput,
        output=DocumentChatOutput,
    )

    graph.add_node(node="prepare_tool_input", action=prepare_tool_input)
    graph.add_node(node="choose_tool", action=choose_tool)
    graph.add_node(node="call_tool", action=call_tool)
    graph.add_node(node="basic_use_tool_response", action=basic_use_tool_response)

    graph.add_edge(start_key=START, end_key="prepare_tool_input")
    graph.add_edge(start_key="prepare_tool_input", end_key="choose_tool")
    graph.add_conditional_edges("choose_tool", should_continue, ["call_tool", END])
    graph.add_edge(start_key="call_tool", end_key="basic_use_tool_response")
    graph.add_conditional_edges(
        "basic_use_tool_response",
        should_repeat,
        ["choose_tool", END],
    )
    return graph


def should_continue(state: DocumentChatState) -> str:
    return END if state.tool_choice is None else "call_tool"


def should_repeat(state: DocumentChatState) -> str:
    if state.tool_choice is None or state.tool_choice.tool.name == "document_editor":
        return END
    return "choose_tool"
