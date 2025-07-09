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


class DRPath(Enum):
    SEARCH = "search"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    CLOSER = "closer"


class OrchestrationUpdate(LoggerUpdate):
    query_path: Annotated[list[DRPath], add] = []
    iteration_nr: int = 0


class AnswerUpdate(LoggerUpdate):
    answers: Annotated[list[str], add] = []
    cited_references: Annotated[list[str], add] = []


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
