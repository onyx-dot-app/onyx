from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.exploration_2.conditional_edges import decision_router
from onyx.agents.agent_search.exploration_2.enums import DRPath
from onyx.agents.agent_search.exploration_2.nodes.dr_a0_opener import opener
from onyx.agents.agent_search.exploration_2.nodes.dr_a1_orchestrator import orchestrator
from onyx.agents.agent_search.exploration_2.nodes.dr_a2_closer import closer
from onyx.agents.agent_search.exploration_2.nodes.dr_a2b_clarifier import clarifier
from onyx.agents.agent_search.exploration_2.nodes.dr_a3a_cs_changes import cs_changes
from onyx.agents.agent_search.exploration_2.nodes.dr_a3b_cs_update_consolidator import (
    cs_update_consolidator,
)
from onyx.agents.agent_search.exploration_2.nodes.dr_a4_logger import logging
from onyx.agents.agent_search.exploration_2.nodes.dr_sa1_query_independent_context_explorer import (
    query_independent_context_explorer,
)
from onyx.agents.agent_search.exploration_2.nodes.dr_sa2_query_dependent_context_explorer import (
    query_dependent_context_explorer,
)
from onyx.agents.agent_search.exploration_2.states import MainInput
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.exploration_2.sub_agents.basic_search.dr_basic_search_graph_builder import (
    dr_basic_search_graph_builder,
)
from onyx.agents.agent_search.exploration_2.sub_agents.custom_tool.dr_custom_tool_graph_builder import (
    dr_custom_tool_graph_builder,
)
from onyx.agents.agent_search.exploration_2.sub_agents.generic_internal_tool.dr_generic_internal_tool_graph_builder import (
    dr_generic_internal_tool_graph_builder,
)
from onyx.agents.agent_search.exploration_2.sub_agents.image_generation.dr_image_generation_graph_builder import (
    dr_image_generation_graph_builder,
)
from onyx.agents.agent_search.exploration_2.sub_agents.kg_search.dr_kg_search_graph_builder import (
    dr_kg_search_graph_builder,
)
from onyx.agents.agent_search.exploration_2.sub_agents.web_search.dr_ws_graph_builder import (
    dr_ws_graph_builder,
)
from onyx.agents.agent_search.exploration_2.tools.dr_sa3_thinking import thinking

# from onyx.agents.agent_search.exploration_2.sub_agents.basic_search.dr_basic_search_2_act import search


def exploration_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the deep research agent.
    """

    graph = StateGraph(state_schema=MainState, input=MainInput)

    ### Add nodes ###

    graph.add_node(DRPath.OPENER, opener)
    graph.add_node(DRPath.CLARIFIER, clarifier)

    graph.add_node(DRPath.ORCHESTRATOR, orchestrator)

    graph.add_node(DRPath.THINKING, thinking)

    basic_search_graph = dr_basic_search_graph_builder().compile()
    graph.add_node(DRPath.INTERNAL_SEARCH, basic_search_graph)

    kg_search_graph = dr_kg_search_graph_builder().compile()
    graph.add_node(DRPath.KNOWLEDGE_GRAPH, kg_search_graph)

    internet_search_graph = dr_ws_graph_builder().compile()
    graph.add_node(DRPath.WEB_SEARCH, internet_search_graph)

    image_generation_graph = dr_image_generation_graph_builder().compile()
    graph.add_node(DRPath.IMAGE_GENERATION, image_generation_graph)

    custom_tool_graph = dr_custom_tool_graph_builder().compile()
    graph.add_node(DRPath.GENERIC_TOOL, custom_tool_graph)

    generic_internal_tool_graph = dr_generic_internal_tool_graph_builder().compile()
    graph.add_node(DRPath.GENERIC_INTERNAL_TOOL, generic_internal_tool_graph)

    graph.add_node(
        DRPath.QUERY_INDEPENDENT_CONTEXT_EXPLORER, query_independent_context_explorer
    )
    graph.add_node(
        DRPath.QUERY_DEPENDENT_CONTEXT_EXPLORER, query_dependent_context_explorer
    )

    graph.add_node(DRPath.CLOSER, closer)
    graph.add_node("cs_changes", cs_changes)
    graph.add_node("cs_consolidator", cs_update_consolidator)
    graph.add_node(DRPath.LOGGER, logging)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key=DRPath.OPENER)

    graph.add_conditional_edges(DRPath.OPENER, decision_router)

    graph.add_conditional_edges(DRPath.ORCHESTRATOR, decision_router)

    graph.add_edge(start_key=DRPath.INTERNAL_SEARCH, end_key=DRPath.ORCHESTRATOR)
    graph.add_edge(start_key=DRPath.KNOWLEDGE_GRAPH, end_key=DRPath.ORCHESTRATOR)
    graph.add_edge(start_key=DRPath.WEB_SEARCH, end_key=DRPath.ORCHESTRATOR)
    graph.add_edge(start_key=DRPath.IMAGE_GENERATION, end_key=DRPath.ORCHESTRATOR)
    graph.add_edge(start_key=DRPath.GENERIC_TOOL, end_key=DRPath.ORCHESTRATOR)
    graph.add_edge(start_key=DRPath.THINKING, end_key=DRPath.ORCHESTRATOR)
    graph.add_edge(
        start_key=DRPath.QUERY_INDEPENDENT_CONTEXT_EXPLORER, end_key=DRPath.ORCHESTRATOR
    )
    graph.add_edge(
        start_key=DRPath.QUERY_DEPENDENT_CONTEXT_EXPLORER, end_key=DRPath.ORCHESTRATOR
    )
    graph.add_edge(start_key=DRPath.GENERIC_INTERNAL_TOOL, end_key=DRPath.ORCHESTRATOR)
    graph.add_edge(start_key=DRPath.CLARIFIER, end_key=DRPath.LOGGER)

    graph.add_edge(DRPath.CLOSER, DRPath.LOGGER)
    # graph.add_conditional_edges("cs_changes", cs_update_consolidator_router)
    # graph.add_edge(start_key="cs_changes", end_key=DRPath.LOGGER)

    graph.add_edge(start_key=DRPath.LOGGER, end_key=END)

    return graph
