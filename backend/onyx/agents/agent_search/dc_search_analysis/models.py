from pydantic import BaseModel


class KGQuestionEntityExtractionResult(BaseModel):
    entities: list[str]
    terms: list[str]
    time_filter: str | None


class KGQuestionRelationshipExtractionResult(BaseModel):
    relationships: list[str]


class KGQuestionExtractionResult(BaseModel):
    entities: list[str]
    relationships: list[str]
    terms: list[str]
    time_filter: str | None
