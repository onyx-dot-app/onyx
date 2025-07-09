from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.conditional_edges import decision_router
from onyx.agents.agent_search.dr.nodes.dr_a1_orchestrator import orchestrator
from onyx.agents.agent_search.dr.nodes.dr_a2_closer import closer
from onyx.agents.agent_search.dr.nodes.dr_i1_search import search
from onyx.agents.agent_search.dr.nodes.dr_i2_kg import kg_query
from onyx.agents.agent_search.kb_search.states import MainInput
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.utils.logger import setup_logger

logger = setup_logger()


def dr_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the knowledge graph  search process.
    """

    graph = StateGraph(
        state_schema=MainState,
        input=MainInput,
    )

    ### Add nodes ###

    graph.add_node(
        "orchestrator",
        orchestrator,
    )

    graph.add_node(
        "search",
        search,
    )

    graph.add_node(
        "kg_query",
        kg_query,
    )

    graph.add_node(
        "closer",
        closer,
    )

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="orchestrator")

    graph.add_conditional_edges("orchestrator", decision_router)

    graph.add_edge(start_key="search", end_key="orchestrator")
    graph.add_edge(start_key="kg_query", end_key="orchestrator")

    graph.add_edge(
        start_key="closer",
        end_key=END,
    )

    return graph
