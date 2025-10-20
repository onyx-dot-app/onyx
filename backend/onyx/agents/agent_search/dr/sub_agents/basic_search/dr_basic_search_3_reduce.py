from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentUpdate
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.context.search.models import SavedSearchDoc
from onyx.context.search.models import SearchDoc
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger


logger = setup_logger()


def is_reducer(
    state: SubAgentMainState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubAgentUpdate:
    """
    LangGraph node to perform a standard search as part of the DR process.
    """

    node_start_time = datetime.now()

    branch_updates = state.branch_iteration_responses
    current_iteration = state.iteration_nr
    current_step_nr = state.current_step_nr

    new_updates = [
        update for update in branch_updates if update.iteration_nr == current_iteration
    ]

    [update.question for update in new_updates]
    doc_lists = [list(update.cited_documents.values()) for update in new_updates]

    doc_list = []

    for xs in doc_lists:
        for x in xs:
            doc_list.append(x)

    # Convert InferenceSections to SavedSearchDocs
    search_docs = SearchDoc.from_chunks_or_sections(doc_list)
    retrieved_saved_search_docs = [
        SavedSearchDoc.from_search_doc(search_doc, db_doc_id=0)
        for search_doc in search_docs
    ]

    for retrieved_saved_search_doc in retrieved_saved_search_docs:
        retrieved_saved_search_doc.is_internet = False

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
                graph_component="basic_search",
                node_name="consolidation",
                node_start_time=node_start_time,
            )
        ],
    )
