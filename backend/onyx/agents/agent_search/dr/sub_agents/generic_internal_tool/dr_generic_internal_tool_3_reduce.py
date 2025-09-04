from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentUpdate
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger


logger = setup_logger()


def generic_internal_tool_reducer(
    state: SubAgentMainState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubAgentUpdate:
    """
    LangGraph node to perform a generic tool call as part of the DR process.
    """

    node_start_time = datetime.now()

    current_step_nr = state.current_step_nr

    branch_updates = state.branch_iteration_responses
    current_iteration = state.iteration_nr

    new_updates = [
        update for update in branch_updates if update.iteration_nr == current_iteration
    ]

    for new_update in new_updates:

        if not new_update.response_type:
            raise ValueError("Response type is not returned.")

        write_custom_event(
            current_step_nr,
            CustomToolStart(
                tool_name=new_update.tool,
            ),
            writer,
        )

        write_custom_event(
            current_step_nr,
            CustomToolDelta(
                tool_name=new_update.tool,
                response_type=new_update.response_type,
                data=new_update.data,
                file_ids=[],
            ),
            writer,
        )

        write_custom_event(
            current_step_nr,
            SectionEnd(),
            writer,
        )

        current_step_nr += 1

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
