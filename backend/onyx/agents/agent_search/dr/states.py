from operator import add
from typing import Annotated
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.dr.models import DRPath
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.dr.models import OrchestrationPlan
from onyx.context.search.models import InferenceSection


### States ###


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class OrchestrationUpdate(LoggerUpdate):
    original_question: str | None = None
    chat_history_string: str | None = None
    query_path: Annotated[list[DRPath | str], add] = []
    query_list: list[str] = []
    iteration_nr: int = 0
    plan_of_record: OrchestrationPlan | None = None  # None for FAST TimeBudget
    remaining_time_budget: float = 2.0  # set by default to about 2 searches
    clarification: OrchestrationClarificationInfo | None = None
    available_tools: list[dict[str, str]] | None = None


class QuestionUpdate(LoggerUpdate):
    iteration_nr: int = 0
    parallelization_nr: int = 0
    question: str | None = None
    tool: DRPath | str | None = None  # needed for custom tools


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
