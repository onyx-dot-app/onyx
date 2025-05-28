from operator import add
from typing import Annotated

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import SubgraphCoreState
from onyx.agents.agent_search.deep_search.main.states import LoggerUpdate
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.models import (
    QuestionRetrievalResult,
)
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.agents.agent_search.shared_graph_utils.models import RetrievalFitStats
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.context.search.models import InferenceSection

### States ###

## Graph Input State


class ExpandedRetrievalInput(SubgraphCoreState):
    # exception from 'no default value'for LangGraph input states
    # Here, sub_question_id default None implies usage for the
    # original question. This is sometimes needed for nested sub-graphs

    sub_question_id: str | None = None
    question: str
    base_search: bool


## Update/Return States


class QueryExpansionUpdate(LoggerUpdate, BaseModel):
    expanded_queries: list[str] = []
    log_messages: list[str] = []


class DocVerificationUpdate(LoggerUpdate, BaseModel):
    verified_documents: Annotated[list[InferenceSection], dedup_inference_sections] = []


class DocRetrievalUpdate(LoggerUpdate, BaseModel):
    query_retrieval_results: Annotated[list[QueryRetrievalResult], add] = []
    retrieved_documents: Annotated[list[InferenceSection], dedup_inference_sections] = (
        []
    )


class DocRerankingUpdate(LoggerUpdate, BaseModel):
    reranked_documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    sub_question_retrieval_stats: RetrievalFitStats | None = None


class ExpandedRetrievalUpdate(LoggerUpdate, BaseModel):
    expanded_retrieval_result: QuestionRetrievalResult


## Graph Output State


class ExpandedRetrievalOutput(LoggerUpdate, BaseModel):
    expanded_retrieval_result: QuestionRetrievalResult = QuestionRetrievalResult()
    base_expanded_retrieval_result: QuestionRetrievalResult = QuestionRetrievalResult()
    retrieved_documents: Annotated[list[InferenceSection], dedup_inference_sections] = (
        []
    )


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
    retrieved_document_to_verify: InferenceSection


class RetrievalInput(ExpandedRetrievalInput):
    query_to_retrieve: str
