from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentUpdate
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger


logger = setup_logger()


def custom_tool_reducer(
    state: SubAgentMainState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubAgentUpdate:
    """
    LangGraph node to perform a generic tool call as part of the DR process.
    """

    node_start_time = datetime.now()

    branch_updates = state.branch_iteration_responses
    current_iteration = state.iteration_nr

    new_updates = [
        update for update in branch_updates if update.iteration_nr == current_iteration
    ]

    return SubAgentUpdate(
        iteration_responses=new_updates,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="custom_tool",
                node_name="consolidation",
                node_start_time=node_start_time,
            )
        ],
    )
