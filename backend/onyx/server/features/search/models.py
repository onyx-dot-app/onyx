from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from onyx.configs.constants import DocumentSource
from onyx.context.search.models import Tag
from onyx.tools.models import ChatMinimalTextMessage

# Public API bound, so internal expansion tuning cannot change it.
MAX_RAW_SEARCH_CONTEXT_CHUNKS = 5


class BaseSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2048)

    sources: list[DocumentSource] | None = None
    document_sets: list[str] | None = None
    tags: list[Tag] | None = None
    # ISO 8601 timestamp. Only documents updated on or after this moment are
    # returned. Naive (timezone-less) values are treated as UTC server-side.
    time_cutoff: datetime | None = None

    persona_id: int | None = None


class SearchRequest(BaseSearchRequest):
    provider: str | None = None
    model: str | None = None

    skip_query_expansion: bool = False

    message_history: list[ChatMinimalTextMessage] | None = None

    @model_validator(mode="after")
    def validate_provider_model_pair(self) -> "SearchRequest":
        if self.model and not self.provider:
            raise ValueError("provider is required when model is specified")
        if self.provider and not self.model:
            raise ValueError("model is required when provider is specified")
        return self


class RawSearchRequest(BaseSearchRequest):
    # Neighboring chunks added on each side of every result.
    context_chunks: int = Field(
        default=MAX_RAW_SEARCH_CONTEXT_CHUNKS, ge=0, le=MAX_RAW_SEARCH_CONTEXT_CHUNKS
    )


class SearchResult(BaseModel):
    citation_id: int | None
    title: str
    # Section text, with any surrounding chunks the search added. Results from
    # one document share a citation_id.
    content: str
    link: str | None
    source_type: str
    updated_at: str | None


class SearchResponse(BaseModel):
    results: list[SearchResult]
