from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_1_branch import (
    is_branch,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_2_search import (
    web_search,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_3_dedup_urls import (
    dedup_urls,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_4_fetch import (
    web_fetch,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_5_collect_raw_docs import (
    collect_raw_docs,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_6_summarize import (
    is_summarize,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_7_reduce import (
    is_reducer,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_conditional_edges import (
    branching_router,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_conditional_edges import (
    fetch_router,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.dr_ws_conditional_edges import (
    summarize_router,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()


def dr_ws_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for Internet Search Sub-Agent
    """

    graph = StateGraph(state_schema=SubAgentMainState, input=SubAgentInput)

    ### Add nodes ###

    graph.add_node("branch", is_branch)

    graph.add_node("search", web_search)

    graph.add_node("dedup_urls", dedup_urls)

    graph.add_node("fetch", web_fetch)

    graph.add_node("collect_raw_docs", collect_raw_docs)

    graph.add_node("summarize", is_summarize)

    graph.add_node("reducer", is_reducer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="branch")

    graph.add_conditional_edges("branch", branching_router)

    graph.add_edge(start_key="search", end_key="dedup_urls")

    graph.add_conditional_edges("dedup_urls", fetch_router)

    graph.add_edge(start_key="fetch", end_key="collect_raw_docs")

    graph.add_conditional_edges("collect_raw_docs", summarize_router)

    graph.add_edge(start_key="summarize", end_key="reducer")

    graph.add_edge(start_key="reducer", end_key=END)

    return graph
