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


class KGAnswerStrategy(Enum):
    DEEP = "DEEP"
    SIMPLE = "SIMPLE"


class AnalysisUpdate(LoggerUpdate):
    normalized_entities: list[str] = []
    normalized_relationships: list[str] = []
    normalized_terms: list[str] = []
    normalized_time_filter: str = ""
    strategy: KGAnswerStrategy | None = None


class SQLGenerationUpdate(LoggerUpdate):
    sql_query: str = ""


class ERTExtractionUpdate(LoggerUpdate):
    entities: list[str] = []
    relationships: list[str] = []
    terms: list[str] = []
    time_filter: str = ""


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
    ERTExtractionUpdate,
    AnalysisUpdate,
    SQLGenerationUpdate,
):
    pass


## Graph Output State - presently not used
class MainOutput(TypedDict):
    log_messages: list[str]
