from operator import add
from typing import Annotated
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.dr.models import DRPath
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import OrchestrationFeedbackRequest
from onyx.agents.agent_search.dr.models import OrchestrationPlan
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.context.search.models import InferenceSection


### States ###


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class OrchestrationUpdate(LoggerUpdate):
    original_question: Annotated[list[str | None], add] = (
        []
    )  # will always be using first
    chat_history_string: str | None = None
    query_path: Annotated[list[DRPath], add] = []
    query_list: list[str] = []
    iteration_nr: int = 0
    plan_of_record: OrchestrationPlan | None = None  # None for FAST TimeBudget
    remaining_time_budget: float = 2.0  # set by default to about 2 searches
    feedback_structure: OrchestrationFeedbackRequest | None = None


class QuestionUpdate(LoggerUpdate):
    iteration_nr: int = 0
    parallelization_nr: int = 0
    question: str | None = None


class AnswerUpdate(LoggerUpdate):
    iteration_responses: Annotated[list[IterationAnswer], add] = []


class FinalUpdate(LoggerUpdate):
    final_answer: str | None = None
    all_cited_documents: list[InferenceSection] = []


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
    OrchestrationUpdate,
    QuestionUpdate,
    AnswerUpdate,
    FinalUpdate,
):
    pass


## Graph Output State
class MainOutput(TypedDict):
    log_messages: list[str]
    final_answer: str | None
    all_cited_documents: list[InferenceSection]
