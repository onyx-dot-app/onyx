from enum import Enum
from operator import add
from typing import Annotated
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate


### States ###


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class DRPath(str, Enum):
    SEARCH = "SEARCH"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    CLOSER = "CLOSER"


class OrchestratorStep(BaseModel):
    tool: DRPath
    questions: list[str]


class OrchestrationUpdate(LoggerUpdate):
    query_path: Annotated[list[DRPath], add] = []
    query_list: list[str] = []
    iteration_nr: int = 0
    plan_of_record: Annotated[list[OrchestratorStep], add] = []
    used_time_budget: int = 0


class SubAgentState(LoggerUpdate):
    iteration_nr: int = 0
    parallelization_nr: int = 0


class SubAgentUpdate(LoggerUpdate):
    iteration_nr: int = 0
    parallelization_nr: int = 0
    iteration_answers: dict[int, dict[int, dict[str, str]]] = {}


class SearchAgentState(SubAgentState):
    pass


class AnswerUpdate(LoggerUpdate):
    iteration_nr: int = 0
    parallelization_nr: int = 0
    instructions: str | None = None
    answers: Annotated[list[str], add] = []
    cited_references: Annotated[list[str], add] = []
    iteration_answers: dict[int, dict[int, dict[str, str]]] = (
        {}
    )  # it, par, {Q, A} TODO: Annotated?


class FinalUpdate(LoggerUpdate):
    pass


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
    AnswerUpdate,
):
    pass


## Graph Output State - presently not used
class MainOutput(TypedDict):
    log_messages: list[str]
