from onyx.agents.agent_search.deep_search_a.base_raw_search.states import (
    BaseRawSearchOutput,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalOutput,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def format_raw_search_results(state: ExpandedRetrievalOutput) -> BaseRawSearchOutput:
    logger.debug("format_raw_search_results")
    return BaseRawSearchOutput(
        base_expanded_retrieval_result=state.expanded_retrieval_result,
        # base_retrieval_results=[state.expanded_retrieval_result],
        # base_search_documents=[],
    )
