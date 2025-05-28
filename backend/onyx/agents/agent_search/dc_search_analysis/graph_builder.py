from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dc_search_analysis.edges import (
    parallel_object_research_consolidation_edge,
)
from onyx.agents.agent_search.dc_search_analysis.edges import (
    parallel_object_source_research_edge,
)
from onyx.agents.agent_search.dc_search_analysis.nodes.a1_search_objects import (
    search_objects,
)
from onyx.agents.agent_search.dc_search_analysis.nodes.a2_research_object_source import (
    research_object_source,
)
from onyx.agents.agent_search.dc_search_analysis.nodes.a3_structure_research_by_object import (
    structure_research_by_object,
)
from onyx.agents.agent_search.dc_search_analysis.nodes.a4_consolidate_object_research import (
    consolidate_object_research,
)
from onyx.agents.agent_search.dc_search_analysis.nodes.a5_consolidate_research import (
    consolidate_research,
)
from onyx.agents.agent_search.dc_search_analysis.states import MainInput
from onyx.agents.agent_search.dc_search_analysis.states import MainState
from onyx.utils.logger import setup_logger

logger = setup_logger()

test_mode = False


def divide_and_conquer_graph_builder(test_mode: bool = False) -> StateGraph:
    """
    LangGraph graph builder for the knowledge graph  search process.
    """

    graph = StateGraph(
        state_schema=MainState,
        input=MainInput,
    )

    ### Add nodes ###

    graph.add_node(
        "search_objects",
        search_objects,
    )

    graph.add_node(
        "structure_research_by_source",
        structure_research_by_object,
    )

    graph.add_node(
        "research_object_source",
        research_object_source,
    )

    graph.add_node(
        "consolidate_object_research",
        consolidate_object_research,
    )

    graph.add_node(
        "consolidate_research",
        consolidate_research,
    )

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="search_objects")

    graph.add_conditional_edges(
        source="search_objects",
        path=parallel_object_source_research_edge,
        path_map=["research_object_source"],
    )

    graph.add_edge(
        start_key="research_object_source",
        end_key="structure_research_by_source",
    )

    graph.add_conditional_edges(
        source="structure_research_by_source",
        path=parallel_object_research_consolidation_edge,
        path_map=["consolidate_object_research"],
    )

    graph.add_edge(
        start_key="consolidate_object_research",
        end_key="consolidate_research",
    )

    graph.add_edge(
        start_key="consolidate_research",
        end_key=END,
    )

    return graph
