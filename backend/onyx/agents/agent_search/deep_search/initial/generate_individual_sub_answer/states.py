from operator import add
from typing import Annotated

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import SubgraphCoreState
from onyx.agents.agent_search.deep_search.main.states import LoggerUpdate
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.agents.agent_search.shared_graph_utils.models import (
    SubQuestionAnswerResults,
)
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.context.search.models import InferenceSection


## Update States
class SubQuestionAnswerCheckUpdate(LoggerUpdate, BaseModel):
    answer_quality: bool = False
    log_messages: list[str] = []


class SubQuestionAnswerGenerationUpdate(LoggerUpdate, BaseModel):
    answer: str = ""
    log_messages: list[str] = []
    cited_documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    # answer_stat: AnswerStats


class SubQuestionRetrievalIngestionUpdate(LoggerUpdate, BaseModel):
    expanded_retrieval_results: list[QueryRetrievalResult] = []
    verified_reranked_documents: Annotated[
        list[InferenceSection], dedup_inference_sections
    ] = []
    context_documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    sub_question_retrieval_stats: AgentChunkRetrievalStats = AgentChunkRetrievalStats()


## Graph Input State


class SubQuestionAnsweringInput(SubgraphCoreState):
    question: str
    question_id: str
    # level 0 is original question and first decomposition, level 1 is follow up, etc
    # question_num is a unique number per original question per level.


## Graph State


class AnswerQuestionState(
    SubQuestionAnsweringInput,
    SubQuestionAnswerGenerationUpdate,
    SubQuestionAnswerCheckUpdate,
    SubQuestionRetrievalIngestionUpdate,
):
    pass


## Graph Output State


class AnswerQuestionOutput(LoggerUpdate, BaseModel):
    """
    This is a list of results even though each call of this subgraph only returns one result.
    This is because if we parallelize the answer query subgraph, there will be multiple
      results in a list so the add operator is used to add them together.
    """

    answer_results: Annotated[list[SubQuestionAnswerResults], add] = []
