from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.conditional_edges import decision_router
from onyx.agents.agent_search.dr.nodes.dr_a0_clarification import clarifier
from onyx.agents.agent_search.dr.nodes.dr_a1_orchestrator import orchestrator
from onyx.agents.agent_search.dr.nodes.dr_a2_closer import closer
from onyx.agents.agent_search.dr.states import DRPath
from onyx.agents.agent_search.dr.states import MainInput
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.sub_agents.basic_search.dr_i1_search import search
from onyx.agents.agent_search.dr.sub_agents.custom_tool_sub_agent.dr_custom_tool_graph_builder import (
    dr_custom_tool_graph_builder,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_graph_builder import (
    dr_is_graph_builder,
)
from onyx.agents.agent_search.dr.sub_agents.kg_search.dr_i2_kg import kg_query
from onyx.utils.logger import setup_logger

logger = setup_logger()


def dr_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the deep research agent.
    """

    graph = StateGraph(state_schema=MainState, input=MainInput)

    ### Add nodes ###

    graph.add_node(DRPath.CLARIFIER.value, clarifier)

    graph.add_node(DRPath.ORCHESTRATOR.value, orchestrator)

    graph.add_node(DRPath.SEARCH.value, search)
    graph.add_node(DRPath.KNOWLEDGE_GRAPH.value, kg_query)

    internet_search_graph = dr_is_graph_builder().compile()
    graph.add_node(DRPath.INTERNET_SEARCH.value, internet_search_graph)

    custom_tool_graph = dr_custom_tool_graph_builder().compile()
    graph.add_node(DRPath.GENERIC_TOOL.value, custom_tool_graph)

    graph.add_node(DRPath.CLOSER.value, closer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key=DRPath.CLARIFIER.value)

    graph.add_conditional_edges(DRPath.CLARIFIER.value, decision_router)

    graph.add_conditional_edges(DRPath.ORCHESTRATOR.value, decision_router)

    graph.add_edge(start_key=DRPath.SEARCH.value, end_key=DRPath.ORCHESTRATOR.value)
    graph.add_edge(
        start_key=DRPath.KNOWLEDGE_GRAPH.value, end_key=DRPath.ORCHESTRATOR.value
    )
    graph.add_edge(
        start_key=DRPath.INTERNET_SEARCH.value, end_key=DRPath.ORCHESTRATOR.value
    )
    graph.add_edge(
        start_key=DRPath.GENERIC_TOOL.value, end_key=DRPath.ORCHESTRATOR.value
    )

    graph.add_edge(start_key=DRPath.CLOSER.value, end_key=END)

    return graph
