from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def basic_search_branch(
    state: SubAgentInput, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> LoggerUpdate:
    """
    LangGraph node to perform a standard search as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr

    logger.debug(f"Search start for Basic Search {iteration_nr} at {datetime.now()}")

    return LoggerUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="basic_search",
                node_name="branching",
                node_start_time=node_start_time,
            )
        ],
    )
