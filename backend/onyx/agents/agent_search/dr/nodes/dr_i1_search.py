from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.basic.graph_builder import basic_graph_builder
from onyx.agents.agent_search.basic.states import BasicInput
from onyx.agents.agent_search.dr.states import AnswerUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def search(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> AnswerUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    search_graph = basic_graph_builder().compile()

    input = BasicInput(unused=True)

    # Stream structure of substeps out to the UI
    # stream_write_basic_search_structure(writer)

    # Now specify core activities in the step (step 1)
    # stream_write_basic_search_activities(writer, step_nr=1)

    # stream_close_step_answer(writer, 1)

    search_results = search_graph.invoke(input=input, config=config)

    full_answer = search_results.get("full_answer") or "No answer provided"

    # stream_write_step_answer_explicit(writer, step_nr=1, answer=full_answer)

    return AnswerUpdate(
        answers=[full_answer],
        cited_references=[],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="kg search",
                node_start_time=node_start_time,
            )
        ],
    )
