from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from onyx.agents.agent_search.document_chat.states import (
    DocumentChatInput,
    DocumentChatOutput,
    DocumentChatState,
)
from onyx.agents.agent_search.orchestration.nodes.edit_node import edit_node
from onyx.agents.agent_search.orchestration.nodes.respond import respond_node
from onyx.agents.agent_search.orchestration.nodes.review_node import review_node
from onyx.agents.agent_search.orchestration.nodes.routers import (
    route_action,
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
    graph.add_node(node="review_node", action=review_node)
    graph.add_node(node="respond_node", action=respond_node)

    graph.add_conditional_edges(
        source=START,
        path=route_thinking,
        path_map={True: "think", False: "action_router"},
    )
    graph.add_edge(start_key="think", end_key="action_router")
    graph.add_conditional_edges(
        source="action_router",
        path=route_action,
        path_map={
            "search": "search_node",
            "edit": "edit_node",
            "review": "review_node",
            "respond": "respond_node",
        },
    )
    graph.add_edge(start_key="search_node", end_key="action_router")
    graph.add_edge(start_key="edit_node", end_key="action_router")
    graph.add_edge(start_key="review_node", end_key="action_router")
    graph.add_edge(start_key="respond_node", end_key=END)

    return graph


def action_router(
    state: DocumentChatState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> dict:
    """Null node to allow routing to search, edit, or response."""
    return {}
