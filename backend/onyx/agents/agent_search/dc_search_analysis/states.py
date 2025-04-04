from operator import add
from typing import Annotated
from typing import Dict
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.configs.constants import DocumentSource


### States ###
class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class SearchSourcesObjectsUpdate(LoggerUpdate):
    analysis_objects: list[str] = []
    analysis_sources: list[DocumentSource] = []


class ObjectSourceInput(LoggerUpdate):
    object_source_combination: tuple[str, DocumentSource]


class ObjectSourceResearchUpdate(LoggerUpdate):
    object_source_research_results: Annotated[list[Dict[str, str]], add] = []


class ObjectInformationInput(LoggerUpdate):
    object_information: Dict[str, str]


class ObjectResearchInformationUpdate(LoggerUpdate):
    object_research_information_results: Annotated[list[Dict[str, str]], add] = []


class ObjectResearchUpdate(LoggerUpdate):
    object_research_results: Annotated[list[Dict[str, str]], add] = []


class ResearchUpdate(LoggerUpdate):
    research_results: str | None = None


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
    SearchSourcesObjectsUpdate,
    ObjectSourceResearchUpdate,
    ObjectResearchInformationUpdate,
    ObjectResearchUpdate,
    ResearchUpdate,
):
    pass


## Graph Output State - presently not used
class MainOutput(TypedDict):
    log_messages: list[str]
