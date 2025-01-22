from collections.abc import Hashable
from typing import cast

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Send

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    RetrievalInput,
)
from onyx.agents.agent_search.models import AgentSearchConfig


def parallel_retrieval_edge(
    state: ExpandedRetrievalState, config: RunnableConfig
) -> list[Send | Hashable]:
    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    question = state.question if state.question else agent_a_config.search_request.query

    query_expansions = (
        state.expanded_queries if state.expanded_queries else [] + [question]
    )
    return [
        Send(
            "doc_retrieval",
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
