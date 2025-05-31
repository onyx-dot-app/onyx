from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.kb_search.conditional_edges import (
    research_individual_object,
)
from onyx.agents.agent_search.kb_search.conditional_edges import simple_vs_search
from onyx.agents.agent_search.kb_search.nodes.a1_extract_ert import extract_ert
from onyx.agents.agent_search.kb_search.nodes.a2_analyze import analyze
from onyx.agents.agent_search.kb_search.nodes.a3_generate_simple_sql import (
    generate_simple_sql,
)
from onyx.agents.agent_search.kb_search.nodes.b1_construct_deep_search_filters import (
    construct_deep_search_filters,
)
from onyx.agents.agent_search.kb_search.nodes.b2p_process_individual_deep_search import (
    process_individual_deep_search,
)
from onyx.agents.agent_search.kb_search.nodes.b2s_filtered_search import filtered_search
from onyx.agents.agent_search.kb_search.nodes.b3_consolidate_individual_deep_search import (
    consolidate_individual_deep_search,
)
from onyx.agents.agent_search.kb_search.nodes.c1_process_kg_only_answers import (
    process_kg_only_answers,
)
from onyx.agents.agent_search.kb_search.nodes.d1_generate_answer import generate_answer
from onyx.agents.agent_search.kb_search.nodes.d2_logging_node import log_data
from onyx.agents.agent_search.kb_search.states import MainInput
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.utils.logger import setup_logger

logger = setup_logger()


def kb_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for the knowledge graph  search process.
    """

    graph = StateGraph(
        state_schema=MainState,
        input=MainInput,
    )

    ### Add nodes ###

    graph.add_node(
        "extract_ert",
        extract_ert,
    )

    graph.add_node(
        "generate_simple_sql",
        generate_simple_sql,
    )

    graph.add_node(
        "filtered_search",
        filtered_search,
    )

    graph.add_node(
        "analyze",
        analyze,
    )

    graph.add_node(
        "generate_answer",
        generate_answer,
    )

    graph.add_node(
        "log_data",
        log_data,
    )

    graph.add_node(
        "construct_deep_search_filters",
        construct_deep_search_filters,
    )

    graph.add_node(
        "process_individual_deep_search",
        process_individual_deep_search,
    )

    graph.add_node(
        "consolidate_individual_deep_search",
        consolidate_individual_deep_search,
    )

    graph.add_node("process_kg_only_answers", process_kg_only_answers)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="extract_ert")

    graph.add_edge(
        start_key="extract_ert",
        end_key="analyze",
    )

    graph.add_edge(
        start_key="analyze",
        end_key="generate_simple_sql",
    )

    graph.add_conditional_edges("generate_simple_sql", simple_vs_search)

    graph.add_edge(start_key="process_kg_only_answers", end_key="generate_answer")

    graph.add_conditional_edges(
        source="construct_deep_search_filters",
        path=research_individual_object,
        path_map=["process_individual_deep_search", "filtered_search"],
    )

    graph.add_edge(
        start_key="process_individual_deep_search",
        end_key="consolidate_individual_deep_search",
    )

    graph.add_edge(
        start_key="consolidate_individual_deep_search", end_key="generate_answer"
    )

    graph.add_edge(
        start_key="filtered_search",
        end_key="generate_answer",
    )

    graph.add_edge(
        start_key="generate_answer",
        end_key="log_data",
    )

    graph.add_edge(
        start_key="log_data",
        end_key=END,
    )

    return graph
