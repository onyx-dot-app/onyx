from typing import TypedDict

from onyx.agent_search.core_state import CoreState
from onyx.agent_search.core_state import SubgraphCoreState
from onyx.agent_search.pro_search_b.expanded_retrieval.models import (
    ExpandedRetrievalResult,
)


## Update States


## Graph Input State


class BaseRawSearchInput(CoreState, SubgraphCoreState):
    pass


## Graph Output State


class BaseRawSearchOutput(TypedDict):
    """
    This is a list of results even though each call of this subgraph only returns one result.
    This is because if we parallelize the answer query subgraph, there will be multiple
      results in a list so the add operator is used to add them together.
    """

    # base_search_documents: Annotated[list[InferenceSection], dedup_inference_sections]
    # base_retrieval_results: Annotated[list[ExpandedRetrievalResult], add]
    base_expanded_retrieval_result: ExpandedRetrievalResult


## Graph State


class BaseRawSearchState(
    BaseRawSearchInput,
    BaseRawSearchOutput,
):
    pass
