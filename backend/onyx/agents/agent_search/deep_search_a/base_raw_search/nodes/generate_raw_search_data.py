from typing import cast

from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.utils.logger import setup_logger

logger = setup_logger()


def generate_raw_search_data(
    state: CoreState, config: RunnableConfig
) -> ExpandedRetrievalInput:
    logger.debug("generate_raw_search_data")
    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    return ExpandedRetrievalInput(
        question=agent_a_config.search_request.query,
        base_search=True,
        sub_question_id=None,  # This graph is always and only used for the original question
        log_messages=[],
    )
