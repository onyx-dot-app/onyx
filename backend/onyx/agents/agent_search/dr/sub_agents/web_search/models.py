from abc import ABC
from abc import abstractmethod
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ProviderType(Enum):
    """Enum for internet search provider types"""

    GOOGLE = "google"
    EXA = "exa"


class InternetSearchResult(BaseModel):
    title: str
    link: str
    author: str | None = None
    published_date: datetime | None = None
    snippet: str | None = None


class InternetContent(BaseModel):
    title: str
    link: str
    full_content: str
    published_date: datetime | None = None


class InternetSearchProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> list[InternetSearchResult]:
        pass

    @abstractmethod
    def contents(self, urls: list[str]) -> list[InternetContent]:
        pass
