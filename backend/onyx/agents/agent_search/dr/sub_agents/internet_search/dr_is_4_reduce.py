from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentUpdate
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger


logger = setup_logger()


def is_reducer(
    state: SubAgentMainState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubAgentUpdate:
    """
    LangGraph node to perform a internet search as part of the DR process.
    """

    node_start_time = datetime.now()

    branch_updates = state.branch_iteration_responses
    current_iteration = state.iteration_nr
    current_step_nr = state.current_step_nr

    new_updates = [
        update for update in branch_updates if update.iteration_nr == current_iteration
    ]

    queries = [update.question for update in new_updates]
    doc_lists = [list(update.cited_documents.values()) for update in new_updates]

    doc_list = []

    for xs in doc_lists:
        for x in xs:
            doc_list.append(x)

    retrieved_search_docs = convert_inference_sections_to_search_docs(
        doc_list, is_internet=True
    )

    # Write the results to the stream
    write_custom_event(
        current_step_nr,
        SearchToolStart(
            is_internet_search=True,
        ),
        writer,
    )

    write_custom_event(
        current_step_nr,
        SearchToolDelta(
            queries=queries,
            documents=retrieved_search_docs,
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
        current_step_nr=current_step_nr,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="consolidation",
                node_start_time=node_start_time,
            )
        ],
    )
