from datetime import datetime

from langchain_core.runnables import RunnableConfig

from onyx.agents.agent_search.dr.states import AnswerUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.kb_search.graph_builder import kb_graph_builder
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def kg_query(state: MainState, config: RunnableConfig) -> AnswerUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    node_start_time = datetime.now()

    kb_graph = kb_graph_builder().compile()

    kb_results = kb_graph.invoke(input=state, config=config)

    return AnswerUpdate(
        answers=[kb_results.get("final_answer") or ""],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="kg search",
                node_start_time=node_start_time,
            )
        ],
    )
