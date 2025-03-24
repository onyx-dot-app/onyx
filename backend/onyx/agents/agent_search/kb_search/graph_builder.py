from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.kb_search.nodes.extract_ert import extract_ert
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

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="extract_ert")

    graph.add_edge(
        start_key="extract_ert",
        end_key=END,
    )

    return graph
