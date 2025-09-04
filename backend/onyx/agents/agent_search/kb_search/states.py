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
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.agents.agent_search.shared_graph_utils.models import SubQuestionAnswerResults
from onyx.context.search.models import InferenceSection


### States ###


class StepResults(BaseModel):
    question: str
    question_id: str
    answer: str
    sub_query_retrieval_results: list[QueryRetrievalResult]
    verified_reranked_documents: list[InferenceSection]
    context_documents: list[InferenceSection]
    cited_documents: list[InferenceSection]


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []
    step_results: Annotated[list[SubQuestionAnswerResults], add]
    remarks: Annotated[list[str], add] = []


class KGFilterConstructionResults(BaseModel):
    global_entity_filters: list[str]
    global_relationship_filters: list[str]
    local_entity_filters: list[list[str]]
    source_document_filters: list[str]
    structure: list[str]


class KGSearchType(Enum):
    SEARCH = "SEARCH"
    SQL = "SQL"


class KGAnswerStrategy(Enum):
    DEEP = "DEEP"
    SIMPLE = "SIMPLE"


class KGSourceDivisionType(Enum):
    SOURCE = "SOURCE"
    ENTITY = "ENTITY"


class KGRelationshipDetection(Enum):
    RELATIONSHIPS = "RELATIONSHIPS"
    NO_RELATIONSHIPS = "NO_RELATIONSHIPS"


class KGAnswerFormat(Enum):
    LIST = "LIST"
    TEXT = "TEXT"


class YesNoEnum(str, Enum):
    YES = "yes"
    NO = "no"


class AnalysisUpdate(LoggerUpdate):
    normalized_core_entities: list[str] = []
    normalized_core_relationships: list[str] = []
    entity_normalization_map: dict[str, str] = {}
    relationship_normalization_map: dict[str, str] = {}
    query_graph_entities_no_attributes: list[str] = []
    query_graph_entities_w_attributes: list[str] = []
    query_graph_relationships: list[str] = []
    normalized_terms: list[str] = []
    normalized_time_filter: str | None = None
    strategy: KGAnswerStrategy | None = None
    output_format: KGAnswerFormat | None = None
    broken_down_question: str | None = None
    divide_and_conquer: YesNoEnum | None = None
    single_doc_id: str | None = None
    search_type: KGSearchType | None = None
    query_type: str | None = None


class SQLSimpleGenerationUpdate(LoggerUpdate):
    sql_query: str | None = None
    sql_query_results: list[Dict[Any, Any]] | None = None
    individualized_sql_query: str | None = None
    individualized_query_results: list[Dict[Any, Any]] | None = None
    source_documents_sql: str | None = None
    source_document_results: list[str] | None = None
    updated_strategy: KGAnswerStrategy | None = None


class ConsolidatedResearchUpdate(LoggerUpdate):
    consolidated_research_object_results_str: str | None = None


class DeepSearchFilterUpdate(LoggerUpdate):
    vespa_filter_results: KGFilterConstructionResults | None = None
    div_con_entities: list[str] | None = None
    source_division: bool | None = None
    global_entity_filters: list[str] | None = None
    global_relationship_filters: list[str] | None = None
    local_entity_filters: list[list[str]] | None = None
    source_filters: list[str] | None = None


class ResearchObjectOutput(LoggerUpdate):
    research_object_results: Annotated[list[dict[str, Any]], add] = []


class EntityRelationshipExtractionUpdate(LoggerUpdate):
    entities_types_str: str = ""
    relationship_types_str: str = ""
    extracted_entities_w_attributes: list[str] = []
    extracted_entities_no_attributes: list[str] = []
    extracted_relationships: list[str] = []
    time_filter: str | None = None
    kg_doc_temp_view_name: str | None = None
    kg_rel_temp_view_name: str | None = None
    kg_entity_temp_view_name: str | None = None


class ResultsDataUpdate(LoggerUpdate):
    query_results_data_str: str | None = None
    individualized_query_results_data_str: str | None = None
    reference_results_str: str | None = None


class ResearchObjectUpdate(LoggerUpdate):
    research_object_results: Annotated[list[dict[str, Any]], add] = []


## Graph Input State
class MainInput(CoreState):
    question: str
    individual_flow: bool = True  # used for UI display purposes


class FinalAnswerUpdate(LoggerUpdate):
    final_answer: str | None = None
    retrieved_documents: list[InferenceSection] | None = None


## Graph State
class MainState(
    # This includes the core state
    MainInput,
    ToolChoiceInput,
    ToolCallUpdate,
    ToolChoiceUpdate,
    EntityRelationshipExtractionUpdate,
    AnalysisUpdate,
    SQLSimpleGenerationUpdate,
    ResultsDataUpdate,
    ResearchObjectOutput,
    DeepSearchFilterUpdate,
    ResearchObjectUpdate,
    ConsolidatedResearchUpdate,
    FinalAnswerUpdate,
):
    pass


## Graph Output State - presently not used
class MainOutput(TypedDict):
    log_messages: list[str]
    final_answer: str | None
    retrieved_documents: list[InferenceSection] | None


class ResearchObjectInput(LoggerUpdate):
    research_nr: int
    entity: str
    broken_down_question: str
    vespa_filter_results: KGFilterConstructionResults
    source_division: bool | None
    source_entity_filters: list[str] | None
    segment_type: str
    individual_flow: bool = True  # used for UI display purposes
