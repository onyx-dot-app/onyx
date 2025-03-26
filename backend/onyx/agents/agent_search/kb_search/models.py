from pydantic import BaseModel


class KGQuestionExtractionResult(BaseModel):
    entities: list[str]
    relationships: list[str]
    terms: list[str]
    time_filter: str
