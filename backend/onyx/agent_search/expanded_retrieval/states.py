from operator import add
from typing import Annotated
from typing import TypedDict

from onyx.agent_search.core_state import SubgraphCoreState
from onyx.agent_search.expanded_retrieval.models import ExpandedRetrievalResult
from onyx.agent_search.expanded_retrieval.models import QueryResult
from onyx.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agent_search.shared_graph_utils.operators import dedup_inference_sections
from onyx.context.search.models import InferenceSection


### States ###

## Graph Input State


class ExpandedRetrievalInput(SubgraphCoreState):
    question: str
    dummy: str


## Update/Return States


class QueryExpansionUpdate(TypedDict):
    expanded_queries: list[str]


class DocVerificationUpdate(TypedDict):
    verified_documents: Annotated[list[InferenceSection], dedup_inference_sections]


class DocRetrievalUpdate(TypedDict):
    expanded_retrieval_results: Annotated[list[QueryResult], add]
    retrieved_documents: Annotated[list[InferenceSection], dedup_inference_sections]


class DocRerankingUpdate(TypedDict):
    reranked_documents: Annotated[list[InferenceSection], dedup_inference_sections]
    sub_question_retrieval_stats: Annotated[list[AgentChunkStats | None], add]


## Graph Output State


class ExpandedRetrievalOutput(TypedDict):
    expanded_retrieval_result: ExpandedRetrievalResult


## Graph State


class ExpandedRetrievalState(
    # This includes the core state
    ExpandedRetrievalInput,
    QueryExpansionUpdate,
    DocRetrievalUpdate,
    DocVerificationUpdate,
    DocRerankingUpdate,
    ExpandedRetrievalOutput,
):
    pass


## Conditional Input States


class DocVerificationInput(ExpandedRetrievalInput):
    doc_to_verify: InferenceSection


class RetrievalInput(ExpandedRetrievalInput):
    query_to_retrieve: str