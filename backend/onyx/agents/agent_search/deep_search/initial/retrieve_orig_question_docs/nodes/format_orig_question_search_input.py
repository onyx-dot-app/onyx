from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()


def format_orig_question_search_input(
    state: CoreState, config: RunnableConfig
) -> ExpandedRetrievalInput:
    """
    LangGraph node to format the search input for the original question.
    """
    logger.debug("generate_raw_search_data")
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    return ExpandedRetrievalInput(
        question=graph_config.inputs.prompt_builder.raw_user_query,
        base_search=True,
        sub_question_id=None,  # This graph is always and only used for the original question
        log_messages=[],
    )
