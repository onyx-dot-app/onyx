from enum import Enum
from operator import add
from typing import Annotated
from typing import Any
from typing import Dict
from typing import TypedDict

from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.orchestration.states import ToolCallUpdate
from onyx.agents.agent_search.orchestration.states import ToolChoiceInput
from onyx.agents.agent_search.orchestration.states import ToolChoiceUpdate
from onyx.agents.agent_search.shared_graph_utils.models import ReferenceResults


### States ###
class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class KGVespaFilterResults(BaseModel):
    entity_filters: list[str]
    relationship_filters: list[str]


class KGAnswerStrategy(Enum):
    DEEP = "DEEP"
    SIMPLE = "SIMPLE"


class KGAnswerFormat(Enum):
    LIST = "LIST"
    TEXT = "TEXT"


class YesNoEnum(str, Enum):
    YES = "yes"
    NO = "no"


class AnalysisUpdate(LoggerUpdate):
    normalized_core_entities: list[str] = []
    normalized_core_relationships: list[str] = []
    query_graph_entities: list[str] = []
    query_graph_relationships: list[str] = []
    normalized_terms: list[str] = []
    normalized_time_filter: str | None = None
    strategy: KGAnswerStrategy | None = None
    output_format: KGAnswerFormat | None = None
    broken_down_question: str | None = None
    divide_and_conquer: YesNoEnum | None = None


class SQLSimpleGenerationUpdate(LoggerUpdate):
    sql_query: str | None = None
    query_results: list[Dict[Any, Any]] | None = None
    individualized_sql_query: str | None = None
    individualized_query_results: list[Dict[Any, Any]] | None = None


class ConsolidatedResearchUpdate(LoggerUpdate):
    consolidated_research_object_results_str: str | None = None


class DeepSearchFilterUpdate(LoggerUpdate):
    vespa_filter_results: KGVespaFilterResults | None = None
    div_con_entities: list[str] | None = None
    source_division: bool | None = None


class ResearchObjectOutput(LoggerUpdate):
    research_object_results: Annotated[list[dict[str, Any]], add] = []


class ERTExtractionUpdate(LoggerUpdate):
    entities_types_str: str = ""
    relationship_types_str: str = ""
    entities: list[str] = []
    relationships: list[str] = []
    terms: list[str] = []
    time_filter: str | None = None


class ResultsDataUpdate(LoggerUpdate):
    query_results_data_str: str | None = None
    individualized_query_results_data_str: str | None = None
    reference_results: ReferenceResults | None = None


class ResearchObjectUpdate(LoggerUpdate):
    research_object_results: Annotated[list[dict[str, Any]], add] = []


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
    SQLSimpleGenerationUpdate,
    ResultsDataUpdate,
    ResearchObjectOutput,
    DeepSearchFilterUpdate,
    ResearchObjectUpdate,
    ConsolidatedResearchUpdate,
):
    pass


## Graph Output State - presently not used
class MainOutput(TypedDict):
    log_messages: list[str]


class ResearchObjectInput(LoggerUpdate):
    entity: str
    broken_down_question: str
    vespa_filter_results: KGVespaFilterResults
    source_division: bool | None
