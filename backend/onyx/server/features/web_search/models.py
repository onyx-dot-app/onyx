from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator

from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmOpenUrlResult,
)
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmWebSearchResult,
)
from shared_configs.enums import WebSearchProviderType


class WebSearchToolRequest(BaseModel):
    queries: list[str] = Field(
        ...,
        min_length=1,
        description="List of search queries to send to the configured provider.",
    )

    @field_validator("queries")
    @classmethod
    def _strip_and_validate_queries(cls, queries: list[str]) -> list[str]:
        cleaned_queries = [q.strip() for q in queries if q and q.strip()]
        if not cleaned_queries:
            raise ValueError("queries must include at least one non-empty value")
        return cleaned_queries


class WebSearchToolResponse(BaseModel):
    results: list[LlmWebSearchResult]
    provider_type: WebSearchProviderType | None = None


class WebSearchWithContentResponse(BaseModel):
    provider_type: WebSearchProviderType | None = None
    search_results: list[LlmWebSearchResult]
    fetched_results: list[LlmOpenUrlResult]


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
