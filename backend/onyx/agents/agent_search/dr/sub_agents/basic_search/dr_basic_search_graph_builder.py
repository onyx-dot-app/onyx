from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.sub_agents.basic_search.dr_basic_search_1_branch import (
    basic_search_branch,
)
from onyx.agents.agent_search.dr.sub_agents.basic_search.dr_basic_search_2_act import (
    basic_search,
)
from onyx.agents.agent_search.dr.sub_agents.basic_search.dr_basic_search_3_reduce import (
    is_reducer,
)
from onyx.agents.agent_search.dr.sub_agents.basic_search.dr_image_generation_conditional_edges import (
    branching_router,
)
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.utils.logger import setup_logger


logger = setup_logger()


def dr_basic_search_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for Web Search Sub-Agent
    """

    graph = StateGraph(state_schema=SubAgentMainState, input=SubAgentInput)

    ### Add nodes ###

    graph.add_node("branch", basic_search_branch)

    graph.add_node("act", basic_search)

    graph.add_node("reducer", is_reducer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="branch")

    graph.add_conditional_edges("branch", branching_router)

    graph.add_edge(start_key="act", end_key="reducer")

    graph.add_edge(start_key="reducer", end_key=END)

    return graph
