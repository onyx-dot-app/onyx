from datetime import datetime

from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.dr.states import FinalUpdate
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def closer(state: MainState, config: RunnableConfig) -> FinalUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    return FinalUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="closer",
                node_start_time=node_start_time,
            )
        ],
    )
