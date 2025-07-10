from enum import Enum
from operator import add
from typing import Annotated
from typing import Dict
from typing import List
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate


### States ###


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class DRPath(Enum):
    SEARCH = "search"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    CLOSER = "closer"


class OrchestrationUpdate(LoggerUpdate):
    query_path: Annotated[list[DRPath], add] = []
    iteration_nr: int = 0
    plan_of_record: Annotated[List[Dict[int, List[Dict[str, str]]]], add] = []
    used_time_budget_int: int = 0


class AnswerUpdate(LoggerUpdate):
    iteration_nr: int = 0
    parallelization_nr: int = 0
    instructions: str | None = None
    answers: Annotated[list[str], add] = []
    cited_references: Annotated[list[str], add] = []
    iteration_answers: Dict[int, Dict[int, Dict[str, str]]] = {}  # it, par, {Q, A}


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
