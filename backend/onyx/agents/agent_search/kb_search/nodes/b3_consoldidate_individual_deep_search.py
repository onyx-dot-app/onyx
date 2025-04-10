from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.kb_search.states import ConsolidatedResearchUpdate
from onyx.agents.agent_search.kb_search.states import MainState
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def consoldidate_individual_deep_search(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> ConsolidatedResearchUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    node_start_time = datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    graph_config.inputs.search_request.query
    state.entities_types_str

    research_object_results = state.research_object_results

    consolidated_research_object_results_str = "\n".join(
        [f"{x['object']}: {x['results']}" for x in research_object_results]
    )

    return ConsolidatedResearchUpdate(
        consolidated_research_object_results_str=consolidated_research_object_results_str,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="generate simple sql",
                node_start_time=node_start_time,
            )
        ],
    )
