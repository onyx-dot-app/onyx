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
from onyx.server.query_and_chat.streaming_models import ReasoningDelta
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger


logger = setup_logger()

_MAX_KG_STEAMED_ANSWER_LENGTH = 1000  # num characters


def kg_search_reducer(
    state: SubAgentMainState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubAgentUpdate:
    """
    LangGraph node to perform a KG search as part of the DR process.
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

    retrieved_search_docs = convert_inference_sections_to_search_docs(doc_list)
    kg_answer = (
        "The Knowledge Graph Answer:\n\n" + new_updates[0].answer
        if len(queries) == 1
        else None
    )

    if len(retrieved_search_docs) > 0:
        write_custom_event(
            current_step_nr,
            SearchToolStart(
                is_internet_search=False,
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

    if kg_answer is not None:

        kg_display_answer = (
            f"{kg_answer[:_MAX_KG_STEAMED_ANSWER_LENGTH]}..."
            if len(kg_answer) > _MAX_KG_STEAMED_ANSWER_LENGTH
            else kg_answer
        )

        write_custom_event(
            current_step_nr,
            ReasoningStart(),
            writer,
        )
        write_custom_event(
            current_step_nr,
            ReasoningDelta(reasoning=kg_display_answer),
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
                graph_component="kg_search",
                node_name="consolidation",
                node_start_time=node_start_time,
            )
        ],
    )
