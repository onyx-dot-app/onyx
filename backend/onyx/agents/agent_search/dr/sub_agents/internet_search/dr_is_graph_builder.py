from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_1_branch import (
    is_branch,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_2_act import (
    internet_search,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_3_reduce import (
    is_reducer,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.dr_is_conditional_edges import (
    branching_router,
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

    graph.add_node("act", internet_search)

    graph.add_node("reducer", is_reducer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="branch")

    graph.add_conditional_edges("branch", branching_router)

    graph.add_edge(start_key="act", end_key="reducer")

    graph.add_edge(start_key="reducer", end_key=END)

    return graph
