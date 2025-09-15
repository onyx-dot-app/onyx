from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    get_default_provider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.states import FetchInput
from onyx.agents.agent_search.dr.sub_agents.web_search.states import FetchUpdate
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    dummy_inference_section_from_internet_content,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.context.search.models import InferenceSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


def web_fetch(
    state: FetchInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> FetchUpdate:
    """
    LangGraph node to fetch content from URLs and process the results.
    """

    node_start_time = datetime.now()

    if not state.available_tools:
        raise ValueError("available_tools is not set")

    graph_config = cast(GraphConfig, config["metadata"]["config"])

    if graph_config.inputs.persona is None:
        raise ValueError("persona is not set")

    provider = get_default_provider()
    if provider is None:
        raise ValueError("No web search provider found")

    retrieved_docs: list[InferenceSection] = []
    try:
        retrieved_docs = [
            dummy_inference_section_from_internet_content(result)
            for result in provider.contents(state.urls_to_open)
        ]
    except Exception as e:
        logger.error(f"Error fetching URLs: {e}")

    if not retrieved_docs:
        logger.warning("No content retrieved from URLs")

    return FetchUpdate(
        raw_documents=retrieved_docs,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="fetching",
                node_start_time=node_start_time,
            )
        ],
    )
