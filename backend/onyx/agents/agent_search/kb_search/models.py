from pydantic import BaseModel

from onyx.agents.agent_search.kb_search.states import KGAnswerFormat
from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import KGRelationshipDetection
from onyx.agents.agent_search.kb_search.states import KGSearchType
from onyx.agents.agent_search.kb_search.states import YesNoEnum


class KGQuestionEntityExtractionResult(BaseModel):
    entities: list[str]
    time_filter: str | None


class KGViewNames(BaseModel):
    allowed_docs_view_name: str
    kg_relationships_view_name: str
    kg_entity_view_name: str


class KGAnswerApproach(BaseModel):
    search_type: KGSearchType
    search_strategy: KGAnswerStrategy
    relationship_detection: KGRelationshipDetection
    format: KGAnswerFormat
    broken_down_question: str | None = None
    divide_and_conquer: YesNoEnum | None = None


class KGQuestionRelationshipExtractionResult(BaseModel):
    relationships: list[str]


class KGQuestionExtractionResult(BaseModel):
    entities: list[str]
    relationships: list[str]
    time_filter: str | None


class KGExpandedGraphObjects(BaseModel):
    entities: list[str]
    relationships: list[str]


class KGSteps(BaseModel):
    description: str
    activities: list[str]


class KGEntityDocInfo(BaseModel):
    doc_id: str | None
    doc_semantic_id: str | None
    doc_link: str | None
    semantic_entity_name: str
    semantic_linked_entity_name: str
