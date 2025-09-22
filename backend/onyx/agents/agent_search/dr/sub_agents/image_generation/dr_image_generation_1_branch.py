from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolStart
from onyx.utils.logger import setup_logger

logger = setup_logger()


def image_generation_branch(
    state: SubAgentInput, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> LoggerUpdate:
    """
    LangGraph node to perform a image generation as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr

    logger.debug(f"Image generation start {iteration_nr} at {datetime.now()}")

    # tell frontend that we are starting the image generation tool
    write_custom_event(
        state.current_step_nr,
        ImageGenerationToolStart(),
        writer,
    )

    return LoggerUpdate(
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="image_generation",
                node_name="branching",
                node_start_time=node_start_time,
            )
        ],
    )
