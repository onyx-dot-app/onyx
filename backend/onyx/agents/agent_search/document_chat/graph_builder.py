from langchain_core.runnables.config import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from onyx.agents.agent_search.document_chat.states import (
    DocumentChatInput,
    DocumentChatOutput,
    DocumentChatState,
)
from onyx.agents.agent_search.orchestration.nodes.respond import respond
from onyx.agents.agent_search.orchestration.nodes.routers import (
    route_action,
    route_thinking,
)
from onyx.agents.agent_search.orchestration.nodes.think import think
from onyx.agents.agent_search.orchestration.nodes.use_tool import use_tool
from onyx.utils.logger import setup_logger

logger = setup_logger()


def document_chat_graph_builder() -> StateGraph:
    graph = StateGraph(
        state_schema=DocumentChatState,
        input=DocumentChatInput,
        output=DocumentChatOutput,
    )
    graph.add_node(node="think", action=think)
    graph.add_node(node="act_or_respond", action=act_or_respond)
    graph.add_node(node="use_tool", action=use_tool)
    graph.add_node(node="respond", action=respond)

    graph.add_conditional_edges(
        source=START,
        path=route_thinking,
        path_map={True: "think", False: "act_or_respond"},
    )
    graph.add_edge(start_key="think", end_key="act_or_respond")
    graph.add_conditional_edges(
        source="act_or_respond",
        path=route_action,
        path_map={True: "use_tool", False: "respond"},
    )
    graph.add_edge(start_key="use_tool", end_key="act_or_respond")
    graph.add_edge(start_key="respond", end_key=END)

    return graph


def act_or_respond(
    state: DocumentChatState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> dict:
    """Null node to allow routing to either tool use or response."""
    return {}
