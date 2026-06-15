from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel
from pydantic import Field
from pydantic import field_validator


class SearchMode(str, Enum):
    LITE = "lite"
    MEDIUM = "medium"
    DEEP = "deep"


class GatewaySearchRequest(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=8)
    mode: SearchMode = SearchMode.LITE
    channel: str | None = None
    max_results: int = Field(default=20, ge=1, le=20)
    locale: str = "zh-CN"

    @field_validator("queries", mode="before")
    @classmethod
    def normalize_queries(cls, value: Any) -> list[str]:
        raw_queries = value if isinstance(value, list) else [value]
        queries: list[str] = []
        seen: set[str] = set()
        for raw_query in raw_queries:
            if raw_query is None:
                continue
            query = _clean_string(str(raw_query))
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
        return queries

    @field_validator("channel")
    @classmethod
    def normalize_channel(cls, value: str | None) -> str | None:
        cleaned = _clean_string(value) if value is not None else None
        return cleaned.lower() if cleaned else None

    @field_validator("locale")
    @classmethod
    def normalize_locale(cls, value: str) -> str:
        return _clean_string(value) or "zh-CN"


class GatewaySearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    author: str | None = None
    published_date: str | None = None


class GatewaySearchResponse(BaseModel):
    results: list[GatewaySearchResult]


def _clean_string(value: str) -> str:
    without_control_chars = "".join(
        char for char in value if ord(char) >= 32 and ord(char) != 127
    )
    return " ".join(without_control_chars.split())
