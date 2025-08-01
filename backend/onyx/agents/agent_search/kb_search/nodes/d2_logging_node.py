from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import MainOutput
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.db.chat import log_agent_sub_question_results
from onyx.utils.logger import setup_logger

logger = setup_logger()


def log_data(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> MainOutput:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])

    search_tool = graph_config.tooling.search_tool
    if search_tool is None:
        raise ValueError("Search tool is not set")

    # commit original db_session

    query_db_session = graph_config.persistence.db_session
    query_db_session.commit()

    chat_session_id = graph_config.persistence.chat_session_id
    primary_message_id = graph_config.persistence.message_id
    sub_question_answer_results = state.step_results

    log_agent_sub_question_results(
        db_session=query_db_session,
        chat_session_id=chat_session_id,
        primary_message_id=primary_message_id,
        sub_question_answer_results=sub_question_answer_results,
    )

    return MainOutput(
        final_answer=state.final_answer,
        retrieved_documents=state.retrieved_documents,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="query completed",
                node_start_time=node_start_time,
            )
        ],
    )
