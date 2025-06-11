from langgraph.graph import END, START, StateGraph

from onyx.agents.agent_search.document_chat.states import (
    DocumentChatInput,
    DocumentChatOutput,
    DocumentChatState,
)
from onyx.agents.agent_search.orchestration.nodes.respond import respond
from onyx.agents.agent_search.orchestration.nodes.use_tool import use_tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def document_chat_graph_builder() -> StateGraph:
    graph = StateGraph(
        state_schema=DocumentChatState,
        input=DocumentChatInput,
        output=DocumentChatOutput,
    )

    graph.add_node(node="use_tool", action=use_tool)
    graph.add_node(node="respond", action=respond)

    graph.add_edge(start_key=START, end_key="use_tool")
    graph.add_edge(start_key="use_tool", end_key="respond")
    graph.add_edge(start_key="respond", end_key=END)

    return graph
