from pydantic import BaseModel
from pydantic import Field
from pydantic import model_validator

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import Tag
from onyx.tools.models import ChatMinimalTextMessage


class SearchAPIRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)

    sources: list[DocumentSource] | None = None
    document_sets: list[str] | None = None
    tags: list[Tag] | None = None
    time_cutoff_days: int | None = Field(None, ge=1)

    persona_id: int | None = None

    provider: str | None = None
    model: str | None = None

    skip_query_expansion: bool = False

    message_history: list[ChatMinimalTextMessage] | None = None

    @model_validator(mode="after")
    def validate_provider_model_pair(self) -> "SearchAPIRequest":
        if self.model and not self.provider:
            raise ValueError("provider is required when model is specified")
        if self.provider and not self.model:
            raise ValueError("model is required when provider is specified")
        return self


class SearchAPIResult(BaseModel):
    citation_id: int | None
    document_id: str
    chunk_ind: int
    title: str
    blurb: str
    link: str | None
    source_type: str
    score: float | None
    updated_at: str | None


class SearchAPIResponse(BaseModel):
    results: list[SearchAPIResult]
    llm_facing_text: str
    citation_mapping: dict[int, str]
