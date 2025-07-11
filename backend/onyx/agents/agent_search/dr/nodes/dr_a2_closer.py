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
    LangGraph node to close the agentic search process and finalize the answer.
    """

    node_start_time = datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)

    return FinalUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="closer",
                node_start_time=node_start_time,
            )
        ],
    )
