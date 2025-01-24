from datetime import datetime
from operator import add
from typing import Annotated
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.models import (
    ExpandedRetrievalResult,
)
from onyx.agents.agent_search.deep_search_a.main.models import AgentBaseMetrics
from onyx.agents.agent_search.deep_search_a.main.models import AgentRefinedMetrics
from onyx.agents.agent_search.deep_search_a.main.models import FollowUpSubQuestion
from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agents.agent_search.shared_graph_utils.models import (
    EntityRelationshipTermExtraction,
)
from onyx.agents.agent_search.shared_graph_utils.models import InitialAgentResultStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryResult
from onyx.agents.agent_search.shared_graph_utils.models import (
    QuestionAnswerResults,
)
from onyx.agents.agent_search.shared_graph_utils.models import RefinedAgentStats
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_inference_sections,
)
from onyx.agents.agent_search.shared_graph_utils.operators import (
    dedup_question_answer_results,
)
from onyx.context.search.models import InferenceSection

### States ###

## Update States


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class RefinedAgentStartStats(BaseModel):
    agent_refined_start_time: datetime | None = None


class RefinedAgentEndStats(BaseModel):
    agent_refined_end_time: datetime | None = None
    agent_refined_metrics: AgentRefinedMetrics = AgentRefinedMetrics()


class BaseDecompUpdateBase(BaseModel):
    agent_start_time: datetime = datetime.now()
    initial_decomp_questions: list[str] = []


class RoutingDecisionBase(BaseModel):
    routing: str = ""
    sample_doc_str: str = ""


class RoutingDecision(RoutingDecisionBase, LoggerUpdate):
    pass


class LoggingUpdate(BaseModel):
    log_messages: list[str] = []


class BaseDecompUpdate(
    RefinedAgentStartStats, RefinedAgentEndStats, BaseDecompUpdateBase
):
    pass


class InitialAnswerBASEUpdate(BaseModel):
    initial_base_answer: str = ""


class InitialAnswerUpdateBase(BaseModel):
    initial_answer: str = ""
    initial_agent_stats: InitialAgentResultStats | None = None
    generated_sub_questions: list[str] = []
    agent_base_end_time: datetime | None = None
    agent_base_metrics: AgentBaseMetrics | None = None


class InitialAnswerUpdate(InitialAnswerUpdateBase, LoggerUpdate):
    pass


class RefinedAnswerUpdateBase(BaseModel):
    refined_answer: str = ""
    refined_agent_stats: RefinedAgentStats | None = None
    refined_answer_quality: bool = False


class RefinedAnswerUpdate(RefinedAgentEndStats, RefinedAnswerUpdateBase):
    pass


class InitialAnswerQualityUpdate(LoggingUpdate):
    initial_answer_quality: bool = False


class RequireRefinedAnswerUpdate(LoggingUpdate):
    require_refined_answer: bool = True


class DecompAnswersUpdate(LoggingUpdate):
    documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    decomp_answer_results: Annotated[
        list[QuestionAnswerResults], dedup_question_answer_results
    ] = []


class FollowUpDecompAnswersUpdate(LoggingUpdate):
    refined_documents: Annotated[list[InferenceSection], dedup_inference_sections] = []
    refined_decomp_answer_results: Annotated[list[QuestionAnswerResults], add] = []


class ExpandedRetrievalUpdate(LoggingUpdate):
    all_original_question_documents: Annotated[
        list[InferenceSection], dedup_inference_sections
    ]
    original_question_retrieval_results: list[QueryResult] = []
    original_question_retrieval_stats: AgentChunkStats = AgentChunkStats()


class EntityTermExtractionUpdateBase(LoggingUpdate):
    entity_retlation_term_extractions: EntityRelationshipTermExtraction = (
        EntityRelationshipTermExtraction()
    )


class EntityTermExtractionUpdate(EntityTermExtractionUpdateBase, LoggerUpdate):
    pass


class FollowUpSubQuestionsUpdateBase(BaseModel):
    refined_sub_questions: dict[int, FollowUpSubQuestion] = {}


class FollowUpSubQuestionsUpdate(
    RefinedAgentStartStats, FollowUpSubQuestionsUpdateBase
):
    pass


## Graph Input State
## Graph Input State


class MainInput(CoreState):
    pass


## Graph State


class MainState(
    # This includes the core state
    MainInput,
    LoggerUpdate,
    BaseDecompUpdateBase,
    InitialAnswerUpdateBase,
    InitialAnswerBASEUpdate,
    DecompAnswersUpdate,
    ExpandedRetrievalUpdate,
    EntityTermExtractionUpdateBase,
    InitialAnswerQualityUpdate,
    RequireRefinedAnswerUpdate,
    FollowUpSubQuestionsUpdateBase,
    FollowUpDecompAnswersUpdate,
    RefinedAnswerUpdateBase,
    RefinedAgentStartStats,
    RefinedAgentEndStats,
    RoutingDecisionBase,
):
    # expanded_retrieval_result: Annotated[list[ExpandedRetrievalResult], add]
    base_raw_search_result: Annotated[list[ExpandedRetrievalResult], add]


## Graph Output State - presently not used


class MainOutput(TypedDict):
    log_messages: list[str]
