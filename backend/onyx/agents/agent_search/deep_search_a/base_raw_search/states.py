from pydantic import BaseModel

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.models import (
    ExpandedRetrievalResult,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)


## Update States


## Graph Input State


class BaseRawSearchInput(ExpandedRetrievalInput):
    pass


## Graph Output State


class BaseRawSearchOutput(BaseModel):
    """
    This is a list of results even though each call of this subgraph only returns one result.
    This is because if we parallelize the answer query subgraph, there will be multiple
      results in a list so the add operator is used to add them together.
    """

    # base_search_documents: Annotated[list[InferenceSection], dedup_inference_sections]
    # base_retrieval_results: Annotated[list[ExpandedRetrievalResult], add]
    base_expanded_retrieval_result: ExpandedRetrievalResult = ExpandedRetrievalResult()


## Graph State


class BaseRawSearchState(
    BaseRawSearchInput,
    BaseRawSearchOutput,
):
    pass
