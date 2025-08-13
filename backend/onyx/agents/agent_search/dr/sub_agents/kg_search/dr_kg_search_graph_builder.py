from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.sub_agents.kg_search.dr_kg_search_1_branch import (
    kg_search_branch,
)
from onyx.agents.agent_search.dr.sub_agents.kg_search.dr_kg_search_2_act import (
    kg_search,
)
from onyx.agents.agent_search.dr.sub_agents.kg_search.dr_kg_search_3_reduce import (
    kg_search_reducer,
)
from onyx.agents.agent_search.dr.sub_agents.kg_search.dr_kg_search_conditional_edges import (
    branching_router,
)
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.utils.logger import setup_logger


logger = setup_logger()


def dr_kg_search_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for KG Search Sub-Agent
    """

    graph = StateGraph(state_schema=SubAgentMainState, input=SubAgentInput)

    ### Add nodes ###

    graph.add_node("branch", kg_search_branch)

    graph.add_node("act", kg_search)

    graph.add_node("reducer", kg_search_reducer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="branch")

    graph.add_conditional_edges("branch", branching_router)

    graph.add_edge(start_key="act", end_key="reducer")

    graph.add_edge(start_key="reducer", end_key=END)

    return graph
