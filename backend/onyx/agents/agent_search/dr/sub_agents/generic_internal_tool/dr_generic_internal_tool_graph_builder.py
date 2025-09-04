from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.sub_agents.generic_internal_tool.dr_generic_internal_tool_1_branch import (
    generic_internal_tool_branch,
)
from onyx.agents.agent_search.dr.sub_agents.generic_internal_tool.dr_generic_internal_tool_2_act import (
    generic_internal_tool_act,
)
from onyx.agents.agent_search.dr.sub_agents.generic_internal_tool.dr_generic_internal_tool_3_reduce import (
    generic_internal_tool_reducer,
)
from onyx.agents.agent_search.dr.sub_agents.generic_internal_tool.dr_generic_internal_tool_conditional_edges import (
    branching_router,
)
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.utils.logger import setup_logger


logger = setup_logger()


def dr_generic_internal_tool_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for Generic Tool Sub-Agent
    """

    graph = StateGraph(state_schema=SubAgentMainState, input=SubAgentInput)

    ### Add nodes ###

    graph.add_node("branch", generic_internal_tool_branch)

    graph.add_node("act", generic_internal_tool_act)

    graph.add_node("reducer", generic_internal_tool_reducer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="branch")

    graph.add_conditional_edges("branch", branching_router)

    graph.add_edge(start_key="act", end_key="reducer")

    graph.add_edge(start_key="reducer", end_key=END)

    return graph
