from operator import add
from typing import Annotated

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import SubgraphCoreState
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryResult
from onyx.agents.agent_search.shared_graph_utils.models import (
    QuestionAnswerResults,
)
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.context.search.models import InferenceSection


## Update States
class QACheckUpdate(BaseModel):
    answer_quality: str = ""
    log_messages: list[str] = []


class QAGenerationUpdate(BaseModel):
    answer: str = ""
    log_messages: list[str] = []
    # answer_stat: AnswerStats


class RetrievalIngestionUpdate(BaseModel):
    expanded_retrieval_results: list[QueryResult] = []
    documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    context_documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    sub_question_retrieval_stats: AgentChunkStats = AgentChunkStats()


## Graph Input State


class AnswerQuestionInput(SubgraphCoreState):
    question: str = ""
    question_id: str = (
        ""  # 0_0 is original question, everything else is <level>_<question_num>.
    )
    # level 0 is original question and first decomposition, level 1 is follow up, etc
    # question_num is a unique number per original question per level.


## Graph State


class AnswerQuestionState(
    AnswerQuestionInput,
    QAGenerationUpdate,
    QACheckUpdate,
    RetrievalIngestionUpdate,
):
    pass


## Graph Output State


class AnswerQuestionOutput(BaseModel):
    """
    This is a list of results even though each call of this subgraph only returns one result.
    This is because if we parallelize the answer query subgraph, there will be multiple
      results in a list so the add operator is used to add them together.
    """

    answer_results: Annotated[list[QuestionAnswerResults], add] = []
