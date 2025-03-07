from datetime import datetime
from operator import add
from typing import Annotated
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.deep_search.main.models import AgentBaseMetrics
from onyx.agents.agent_search.deep_search.main.models import (
    AgentRefinedMetrics,
)
from onyx.agents.agent_search.deep_search.main.models import (
    RefinementSubQuestion,
)
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.agents.agent_search.shared_graph_utils.models import AgentErrorLog
from onyx.agents.agent_search.shared_graph_utils.models import (
    EntityRelationshipTermExtraction,
)
from onyx.agents.agent_search.shared_graph_utils.models import InitialAgentResultStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.agents.agent_search.shared_graph_utils.models import RefinedAgentStats
from onyx.agents.agent_search.shared_graph_utils.models import (
    SubQuestionAnswerResults,
)
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_question_answer_results,
)
from onyx.context.search.models import InferenceSection


### States ###
class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class RefinedAgentStartStats(BaseModel):
    agent_refined_start_time: datetime | None = None


class RefinedAgentEndStats(BaseModel):
    agent_refined_end_time: datetime | None = None
    agent_refined_metrics: AgentRefinedMetrics = AgentRefinedMetrics()


class InitialQuestionDecompositionUpdate(
    RefinedAgentStartStats, RefinedAgentEndStats, LoggerUpdate
):
    agent_start_time: datetime | None = None
    previous_history: str | None = None
    initial_sub_questions: list[str] = []


class ExploratorySearchUpdate(LoggerUpdate):
    exploratory_search_results: list[InferenceSection] = []
    previous_history_summary: str | None = None


class InitialRefinedAnswerComparisonUpdate(LoggerUpdate):
    """
    Evaluation of whether the refined answer is better than the initial answer
    """

    refined_answer_improvement_eval: bool = False


class InitialAnswerUpdate(LoggerUpdate):
    """
    Initial answer information
    """

    initial_answer: str | None = None
    answer_error: AgentErrorLog | None = None
    initial_agent_stats: InitialAgentResultStats | None = None
    generated_sub_questions: list[str] = []
    agent_base_end_time: datetime | None = None
    agent_base_metrics: AgentBaseMetrics | None = None


class RefinedAnswerUpdate(RefinedAgentEndStats, LoggerUpdate):
    """
    Refined answer information
    """

    refined_answer: str | None = None
    answer_error: AgentErrorLog | None = None
    refined_agent_stats: RefinedAgentStats | None = None
    refined_answer_quality: bool = False


class InitialAnswerQualityUpdate(LoggerUpdate):
    """
    Initial answer quality evaluation
    """

    initial_answer_quality_eval: bool = False


class RequireRefinemenEvalUpdate(LoggerUpdate):
    require_refined_answer_eval: bool = True


class SubQuestionResultsUpdate(LoggerUpdate):
    verified_reranked_documents: Annotated[
        list[InferenceSection], dedup_inference_sections
    ] = []
    context_documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    cited_documents: Annotated[
        list[InferenceSection], dedup_inference_sections
    ] = []  # cited docs from sub-answers are used for answer context
    sub_question_results: Annotated[
        list[SubQuestionAnswerResults], dedup_question_answer_results
    ] = []


class OrigQuestionRetrievalUpdate(LoggerUpdate):
    orig_question_retrieved_documents: Annotated[
        list[InferenceSection], dedup_inference_sections
    ]
    orig_question_verified_reranked_documents: Annotated[
        list[InferenceSection], dedup_inference_sections
    ]
    orig_question_sub_query_retrieval_results: list[QueryRetrievalResult] = []
    orig_question_retrieval_stats: AgentChunkRetrievalStats = AgentChunkRetrievalStats()


class EntityTermExtractionUpdate(LoggerUpdate):
    entity_relation_term_extractions: EntityRelationshipTermExtraction = (
        EntityRelationshipTermExtraction()
    )


class RefinedQuestionDecompositionUpdate(RefinedAgentStartStats, LoggerUpdate):
    refined_sub_questions: dict[int, RefinementSubQuestion] = {}


## Graph Input State
class MainInput(CoreState):
    pass


## Graph State
class MainState(
    # This includes the core state
    MainInput,
    ToolChoiceInput,
    ToolCallUpdate,
    ToolChoiceUpdate,
    InitialQuestionDecompositionUpdate,
    InitialAnswerUpdate,
    SubQuestionResultsUpdate,
    OrigQuestionRetrievalUpdate,
    EntityTermExtractionUpdate,
    InitialAnswerQualityUpdate,
    RequireRefinemenEvalUpdate,
    RefinedQuestionDecompositionUpdate,
    RefinedAnswerUpdate,
    RefinedAgentStartStats,
    RefinedAgentEndStats,
    InitialRefinedAnswerComparisonUpdate,
    ExploratorySearchUpdate,
):
    pass


## Graph Output State - presently not used
class MainOutput(TypedDict):
    log_messages: list[str]
