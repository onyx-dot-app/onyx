from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.custom_tool_sub_agent.dr_custom_tool_states import (
    CustomToolSubAgentInput,
)
from onyx.agents.agent_search.dr.sub_agents.custom_tool_sub_agent.dr_custom_tool_states import (
    CustomToolSubAgentPrepareUpdate,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def custom_tool_branch(
    state: CustomToolSubAgentInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> CustomToolSubAgentPrepareUpdate:
    """
    LangGraph node to perform a generic tool call as part of the DR process.
    """

    node_start_time = datetime.now()
    tool_name = state.query_path[-1]

    if state.available_tools is None:
        raise ValueError("available_tools is not set")

    for available_tool_dict in state.available_tools:
        if available_tool_dict["name"] == tool_name:
            tool_dict = available_tool_dict
            break

    return CustomToolSubAgentPrepareUpdate(
        tool_name=tool_name,
        tool_dict=tool_dict,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="custom_tool_sub_agent",
                node_name="branching",
                node_start_time=node_start_time,
            )
        ],
    )
