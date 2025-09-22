from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agents.agent_search.dr.sub_agents.image_generation.dr_image_generation_1_branch import (
    image_generation_branch,
)
from onyx.agents.agent_search.dr.sub_agents.image_generation.dr_image_generation_2_act import (
    image_generation,
)
from onyx.agents.agent_search.dr.sub_agents.image_generation.dr_image_generation_3_reduce import (
    is_reducer,
)
from onyx.agents.agent_search.dr.sub_agents.image_generation.dr_image_generation_conditional_edges import (
    branching_router,
)
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.utils.logger import setup_logger


logger = setup_logger()


def dr_image_generation_graph_builder() -> StateGraph:
    """
    LangGraph graph builder for Image Generation Sub-Agent
    """

    graph = StateGraph(state_schema=SubAgentMainState, input=SubAgentInput)

    ### Add nodes ###

    graph.add_node("branch", image_generation_branch)

    graph.add_node("act", image_generation)

    graph.add_node("reducer", is_reducer)

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="branch")

    graph.add_conditional_edges("branch", branching_router)

    graph.add_edge(start_key="act", end_key="reducer")

    graph.add_edge(start_key="reducer", end_key=END)

    return graph
