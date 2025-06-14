from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from onyx.agents.agent_search.document_chat.states import (
    DocumentChatInput,
    DocumentChatOutput,
    DocumentChatState,
)
from onyx.agents.agent_search.orchestration.nodes.edit_node import edit_node
from onyx.agents.agent_search.orchestration.nodes.respond import respond
from onyx.agents.agent_search.orchestration.nodes.routers import (
    route_action_three_way,
    route_thinking,
)
from onyx.agents.agent_search.orchestration.nodes.search_node import search_node
from onyx.agents.agent_search.orchestration.nodes.think import think
from onyx.utils.logger import setup_logger

logger = setup_logger()


def document_chat_graph_builder() -> StateGraph:
    graph = StateGraph(
        state_schema=DocumentChatState,
        input=DocumentChatInput,
        output=DocumentChatOutput,
    )
    graph.add_node(node="think", action=think)
    graph.add_node(node="action_router", action=action_router)
    graph.add_node(node="search_node", action=search_node)
    graph.add_node(node="edit_node", action=edit_node)
    graph.add_node(node="respond", action=respond)

    graph.add_conditional_edges(
        source=START,
        path=route_thinking,
        path_map={True: "think", False: "action_router"},
    )
    graph.add_edge(start_key="think", end_key="action_router")
    graph.add_conditional_edges(
        source="action_router",
        path=route_action_three_way,
        path_map={"search": "search_node", "edit": "edit_node", "respond": "respond"},
    )
    graph.add_edge(start_key="search_node", end_key="action_router")  # Allow multiple searches
    graph.add_edge(start_key="edit_node", end_key="respond")          # Edit then respond
    graph.add_edge(start_key="respond", end_key=END)

    return graph


def action_router(
    state: DocumentChatState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> dict:
    """Null node to allow routing to search, edit, or response."""
    return {}
