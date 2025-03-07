from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    QueryExpansionUpdate,
)


def format_queries(
    state: ExpandedRetrievalState, config: RunnableConfig
) -> QueryExpansionUpdate:
    """
    LangGraph node to format the expanded queries into a list of strings.
    """
    return QueryExpansionUpdate(
        expanded_queries=state.expanded_queries,
    )
