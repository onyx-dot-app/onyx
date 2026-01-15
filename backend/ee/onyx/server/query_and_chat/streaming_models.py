from typing import Literal

from pydantic import BaseModel

from onyx.context.search.models import SearchDoc


class SearchQueriesPacket(BaseModel):
    type: Literal["search_queries"] = "search_queries"
    all_executed_queries: list[str]


class SearchDocsPacket(BaseModel):
    type: Literal["search_docs"] = "search_docs"
    search_docs: list[SearchDoc]


class SearchErrorPacket(BaseModel):
    type: Literal["search_error"] = "search_error"
    error: str
