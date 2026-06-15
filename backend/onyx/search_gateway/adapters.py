from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from typing import Protocol

from onyx.search_gateway.models import GatewaySearchResult
from onyx.search_gateway.models import SearchMode

SearchDepth = Literal["basic", "advanced"]


@dataclass(frozen=True)
class SearchAdapterCapabilities:
    channel: str
    supports_basic_search: bool = True
    supports_advanced_search: bool = False
    supports_raw_content: bool = False
    supports_extract: bool = False


@dataclass(frozen=True)
class SearchAdapterOptions:
    mode: SearchMode
    search_depth: SearchDepth
    max_results: int
    include_raw_content: bool
    raw_content_max_chars: int | None
    locale: str


class SearchAdapter(Protocol):
    @property
    def capabilities(self) -> SearchAdapterCapabilities:
        pass

    def search(
        self,
        *,
        query: str,
        options: SearchAdapterOptions,
    ) -> list[GatewaySearchResult]:
        pass
