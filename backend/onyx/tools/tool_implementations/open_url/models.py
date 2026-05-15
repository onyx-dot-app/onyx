from abc import ABC
from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime

from pydantic import BaseModel
from pydantic import field_validator

from onyx.utils.url import normalize_url


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
