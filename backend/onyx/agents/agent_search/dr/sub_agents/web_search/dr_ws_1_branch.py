from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.utils.logger import setup_logger

logger = setup_logger()


def is_branch(
    state: SubAgentInput, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> LoggerUpdate:
    """
    LangGraph node to perform a web search as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    current_step_nr = state.current_step_nr

    logger.debug(f"Search start for Web Search {iteration_nr} at {datetime.now()}")

    write_custom_event(
        current_step_nr,
        SearchToolStart(
            is_internet_search=True,
        ),
        writer,
    )

    return LoggerUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="branching",
                node_start_time=node_start_time,
            )
        ],
    )
