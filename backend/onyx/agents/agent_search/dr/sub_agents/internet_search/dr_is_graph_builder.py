from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_1_branch import (
    is_branch,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_2_search import (
    web_search,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_3_fetch import (
    web_fetch,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_4_reduce import (
    is_reducer,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_conditional_edges import (
    branching_router,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_conditional_edges import (
    fetch_router,
)
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.utils.logger import setup_logger


logger = setup_logger()


def dr_is_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for Internet Search Sub-Agent
    """

    graph = StateGraph(state_schema=SubAgentMainState, input=SubAgentInput)

    ### Add nodes ###

    graph.add_node("branch", is_branch)

    graph.add_node("search", web_search)

    graph.add_node("fetch", web_fetch)

    graph.add_node("reducer", is_reducer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="branch")

    graph.add_conditional_edges("branch", branching_router)

    graph.add_conditional_edges("search", fetch_router)

    # Fallback edge from search to reducer when no URLs are found
    # graph.add_edge(start_key="search", end_key="reducer")

    graph.add_edge(start_key="fetch", end_key="reducer")

    graph.add_edge(start_key="reducer", end_key=END)

    return graph
