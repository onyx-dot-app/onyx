from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticKnownError

from onyx.utils.text_processing import unique_stripped
from onyx.utils.url import normalize_url


class OpenURLArguments(BaseModel):
    urls: list[str] = Field(
        description=(
            "List of URLs to open and read, can be a single URL or multiple URLs. "
            "This will return the text content of the page(s)."
        )
    )

    @field_validator("urls", mode="before")
    @classmethod
    def clean_urls(cls, value: object) -> list[str]:
        """Accept a bare URL or null. Strip each URL and drop empty and
        repeated ones, keeping the first order. With no URL left, the argument
        is missing."""
        if value is None:
            value = []
        elif isinstance(value, str):
            value = [value]
        elif not isinstance(value, list):
            raise ValueError("Provide urls as a string or a list of strings.")
        urls = unique_stripped(str(item) for item in value)
        if not urls:
            raise PydanticKnownError("missing")
        return urls


class WebContent(BaseModel):
    title: str
    link: str
    full_content: str
    published_date: datetime | None = None
    scrape_successful: bool = True
    # Short, LLM-/admin-facing explanation of why a fetch failed (set when
    # `scrape_successful=False`). Examples: "blocked by a Cloudflare bot
    # challenge — try a different URL or configure Firecrawl as the web
    # content provider", "request timed out", "404 not found".
    failure_reason: str | None = None

    @field_validator("link")
    @classmethod
    def normalize_link(cls, v: str) -> str:
        return normalize_url(v)


class FailedFetch(BaseModel):
    """A URL that the open_url tool could not retrieve, with the reason."""

    url: str
    failure_reason: str | None = None


class WebContentProvider(ABC):
    @abstractmethod
    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        pass
