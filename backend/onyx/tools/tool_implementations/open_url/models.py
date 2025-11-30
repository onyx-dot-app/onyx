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

    @field_validator("link")
    @classmethod
    def normalize_link(cls, v: str) -> str:
        return normalize_url(v)


class WebContentProvider(ABC):
    @abstractmethod
    def contents(self, urls: Sequence[str]) -> list[WebContent]:
        pass
