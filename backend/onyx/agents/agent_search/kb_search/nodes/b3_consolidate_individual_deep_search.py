from datetime import datetime

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.graph_utils import get_near_empty_step_results
from onyx.agents.agent_search.kb_search.graph_utils import rename_entities_in_answer
from onyx.agents.agent_search.kb_search.states import ConsolidatedResearchUpdate
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def consolidate_individual_deep_search(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ConsolidatedResearchUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    _KG_STEP_NR = 4
    node_start_time = datetime.now()

    research_object_results = state.research_object_results

    consolidated_research_object_results_str = "\n".join(
        [f"{x['object']}: {x['results']}" for x in research_object_results]
    )

    consolidated_research_object_results_str = rename_entities_in_answer(
        consolidated_research_object_results_str
    )

    step_answer = "All research is complete. Consolidating results..."

    return ConsolidatedResearchUpdate(
        consolidated_research_object_results_str=consolidated_research_object_results_str,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="consolidate individual deep search",
                node_start_time=node_start_time,
            )
        ],
        step_results=[
            get_near_empty_step_results(
                step_number=_KG_STEP_NR, step_answer=step_answer
            )
        ],
    )
