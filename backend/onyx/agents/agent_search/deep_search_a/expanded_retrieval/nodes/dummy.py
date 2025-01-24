from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    QueryExpansionUpdate,
)


def dummy(
    state: ExpandedRetrievalState, config: RunnableConfig
) -> QueryExpansionUpdate:
    return QueryExpansionUpdate(
        expanded_queries=state.expanded_queries,
    )
