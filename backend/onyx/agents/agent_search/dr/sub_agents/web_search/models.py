from abc import ABC
from abc import abstractmethod
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ProviderType(Enum):
    """Enum for internet search provider types"""

    GOOGLE = "google"
    EXA = "exa"


class WebSearchResult(BaseModel):
    title: str
    link: str
    author: str | None = None
    published_date: datetime | None = None
    snippet: str | None = None


class WebContent(BaseModel):
    title: str
    link: str
    full_content: str
    published_date: datetime | None = None
    scrape_successful: bool = True


class WebSearchProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> list[WebSearchResult]:
        pass

    @abstractmethod
    def contents(self, urls: list[str]) -> list[WebContent]:
        pass
