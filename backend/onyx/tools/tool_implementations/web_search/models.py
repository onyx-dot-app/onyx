from abc import abstractmethod
from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticKnownError

from onyx.utils.url import normalize_url

# Fairly loose number but assuming LLMs can easily handle this amount of context
# Approximately 2 pages of google search results
# This is the cap for both when the tool is running a single search and when running multiple queries in parallel
DEFAULT_MAX_RESULTS = 20

WEB_SEARCH_PREFIX = "WEB_SEARCH_DOC_"


class ProviderType(Enum):
    """Enum for internet search provider types"""

    GOOGLE = "google"
    EXA = "exa"


class WebSearchArguments(BaseModel):
    queries: list[str] = Field(
        description="One or more queries to look up on the web. Must contain only printable characters"
    )

    @field_validator("queries", mode="before")
    @classmethod
    def sanitize_queries(cls, raw: object) -> list[str]:
        """Accept a bare string or a list of any values. Remove control
        characters, collapse whitespace and drop empty queries. With no query
        left, the argument is missing."""
        if isinstance(raw, str):
            raw = [raw]
        elif not isinstance(raw, list):
            raw = []
        sanitized = (
            " ".join(
                "".join(
                    char for char in str(item) if ord(char) >= 32 and ord(char) != 127
                ).split()
            )
            for item in raw
            if item is not None
        )
        queries = [query for query in sanitized if query]
        if not queries:
            raise PydanticKnownError("missing")
        return queries


class WebSearchResult(BaseModel):
    title: str
    link: str
    snippet: str
    author: str | None = None
    published_date: datetime | None = None

    @field_validator("link")
    @classmethod
    def normalize_link(cls, v: str) -> str:
        return normalize_url(v)


class WebSearchProvider:
    @property
    def supports_site_filter(self) -> bool:
        """Whether this provider supports the site: operator in queries.
        Override in subclasses that don't support it.
        """
        return True

    @abstractmethod
    def search(self, query: str) -> Sequence[WebSearchResult]:
        pass

    @abstractmethod
    def test_connection(self) -> dict[str, str]:
        pass


class WebContentProviderConfig(BaseModel):
    timeout_seconds: int | None = None
    base_url: str | None = None
