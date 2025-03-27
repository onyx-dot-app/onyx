from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.kb_search.nodes.analyze import analyze
from onyx.agents.agent_search.kb_search.nodes.extract_ert import extract_ert
from onyx.agents.agent_search.kb_search.nodes.generate_simple_sql import (
    generate_simple_sql,
)
from onyx.agents.agent_search.kb_search.states import MainInput
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.utils.logger import setup_logger

logger = setup_logger()

test_mode = False


def kb_graph_builder(test_mode: bool = False) -> StateGraph:
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
        "analyze",
        analyze,
    )

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

    graph.add_edge(
        start_key="generate_simple_sql",
        end_key=END,
    )

    return graph
