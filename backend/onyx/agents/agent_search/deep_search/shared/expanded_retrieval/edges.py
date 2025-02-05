from collections.abc import Hashable
from typing import cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Send

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    RetrievalInput,
)
from onyx.agents.agent_search.models import GraphConfig


def parallel_retrieval_edge(
    state: ExpandedRetrievalState, config: RunnableConfig
) -> list[Send | Hashable]:
    """
    LangGraph edge to parallelize the retrieval process for each of the
    generated sub-queries and the original question.
    """
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = (
        state.question if state.question else graph_config.inputs.search_request.query
    )

    query_expansions = state.expanded_queries + [question]

    return [
        Send(
            "retrieve_documents",
            RetrievalInput(
                query_to_retrieve=query,
                question=question,
                base_search=False,
                sub_question_id=state.sub_question_id,
                log_messages=[],
            ),
        )
        for query in query_expansions
    ]
