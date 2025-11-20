from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmOpenUrlResult,
)
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmWebSearchResult,
)
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType


class WebSearchToolRequest(BaseModel):
    queries: list[str] = Field(
        ...,
        min_length=1,
        description="List of search queries to send to the configured provider.",
    )
    max_results: int | None = Field(
        default=10,
        description=(
            "Optional cap on number of results to return per query. Defaults to 10."
        ),
    )

    @field_validator("queries")
    @classmethod
    def _strip_and_validate_queries(cls, queries: list[str]) -> list[str]:
        cleaned_queries = [q.strip() for q in queries if q and q.strip()]
        if not cleaned_queries:
            raise ValueError("queries must include at least one non-empty value")
        return cleaned_queries

    @field_validator("max_results")
    @classmethod
    def _default_and_validate_max_results(cls, max_results: int | None) -> int:
        # Default to 10 when not provided
        max_results = 10 if max_results is None else max_results
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        return max_results


class WebSearchToolResponse(BaseModel):
    results: list[LlmWebSearchResult]
    provider_type: WebSearchProviderType


class WebSearchWithContentResponse(BaseModel):
    search_provider_type: WebSearchProviderType
    content_provider_type: WebContentProviderType | None = None
    search_results: list[LlmWebSearchResult]
    full_content_results: list[LlmOpenUrlResult]


class OpenUrlsToolRequest(BaseModel):
    urls: list[str] = Field(
        ...,
        min_length=1,
        description="URLs to fetch using the configured content provider.",
    )

    @field_validator("urls")
    @classmethod
    def _strip_and_validate_urls(cls, urls: list[str]) -> list[str]:
        cleaned_urls = [url.strip() for url in urls if url and url.strip()]
        if not cleaned_urls:
            raise ValueError("urls must include at least one non-empty value")
        return cleaned_urls


class OpenUrlsToolResponse(BaseModel):
    results: list[LlmOpenUrlResult]
    provider_type: WebContentProviderType | None = None
