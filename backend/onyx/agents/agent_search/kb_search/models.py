from pydantic import BaseModel

from onyx.agents.agent_search.kb_search.states import KGAnswerFormat
from onyx.agents.agent_search.kb_search.states import KGAnswerStrategy
from onyx.agents.agent_search.kb_search.states import YesNoEnum


class KGQuestionEntityExtractionResult(BaseModel):
    entities: list[str]
    terms: list[str]
    time_filter: str | None


class KGAnswerApproach(BaseModel):
    strategy: KGAnswerStrategy
    format: KGAnswerFormat
    broken_down_question: str | None = None
    divide_and_conquer: YesNoEnum | None = None


class KGQuestionRelationshipExtractionResult(BaseModel):
    relationships: list[str]


class KGQuestionExtractionResult(BaseModel):
    entities: list[str]
    relationships: list[str]
    terms: list[str]
    time_filter: str | None


class KGExpendedGraphObjects(BaseModel):
    entities: list[str]
    relationships: list[str]
