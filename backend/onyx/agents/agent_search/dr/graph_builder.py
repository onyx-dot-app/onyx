from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.conditional_edges import decision_router
from onyx.agents.agent_search.dr.nodes.dr_a1_orchestrator import orchestrator
from onyx.agents.agent_search.dr.nodes.dr_a2_closer import closer
from onyx.agents.agent_search.dr.nodes.dr_i1_search import search
from onyx.agents.agent_search.dr.nodes.dr_i2_kg import kg_query
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainInput
from onyx.agents.agent_search.dr.states import MainState
from onyx.utils.logger import setup_logger

logger = setup_logger()


def dr_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the deep research agent.
    """

    graph = StateGraph(state_schema=MainState, input=MainInput)

    ### Add nodes ###

    graph.add_node("orchestrator", orchestrator)

    graph.add_node(DRPath.SEARCH, search)
    graph.add_node(DRPath.KNOWLEDGE_GRAPH, kg_query)

    graph.add_node(DRPath.CLOSER, closer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="orchestrator")

    graph.add_conditional_edges("orchestrator", decision_router)

    graph.add_edge(start_key=DRPath.SEARCH, end_key="orchestrator")
    graph.add_edge(start_key=DRPath.KNOWLEDGE_GRAPH, end_key="orchestrator")

    graph.add_edge(start_key=DRPath.CLOSER, end_key=END)

    return graph
