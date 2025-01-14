from collections.abc import Hashable

from langgraph.types import Send

from onyx.agent_search.core_state import in_subgraph_extract_core_fields
from onyx.agent_search.pro_search_a.expanded_retrieval.nodes import RetrievalInput
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    ExpandedRetrievalState,
)


def parallel_retrieval_edge(state: ExpandedRetrievalState) -> list[Send | Hashable]:
    question = state.get("question", state["subgraph_config"].search_request.query)

    query_expansions = state.get("expanded_queries", []) + [question]
    return [
        Send(
            "doc_retrieval",
            RetrievalInput(
                query_to_retrieve=query,
                question=question,
                **in_subgraph_extract_core_fields(state),
                base_search=False,
                sub_question_id=state.get("sub_question_id"),
            ),
        )
        for query in query_expansions
    ]
