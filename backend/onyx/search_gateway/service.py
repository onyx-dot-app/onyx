from __future__ import annotations

from collections.abc import Iterable

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.search_gateway.adapters import SearchAdapter
from onyx.search_gateway.adapters import SearchAdapterCapabilities
from onyx.search_gateway.adapters import SearchAdapterOptions
from onyx.search_gateway.adapters import SearchDepth
from onyx.search_gateway.models import GatewaySearchRequest
from onyx.search_gateway.models import GatewaySearchResponse
from onyx.search_gateway.models import GatewaySearchResult
from onyx.search_gateway.models import SearchMode
from onyx.search_gateway.query_planner import build_effective_queries

MEDIUM_RAW_CONTENT_SNIPPET_MAX_CHARS = 800
DEEP_RAW_CONTENT_SNIPPET_MAX_CHARS = 1200


class SearchGatewayService:
    def __init__(
        self,
        *,
        adapters: Iterable[SearchAdapter],
        default_channel: str,
    ) -> None:
        self._default_channel = _normalize_channel(default_channel)
        self._adapters = {
            _normalize_channel(adapter.capabilities.channel): adapter
            for adapter in adapters
        }

    def search(self, request: GatewaySearchRequest) -> GatewaySearchResponse:
        adapter = self._adapter_for_request(request)
        effective_queries = build_effective_queries(
            request.queries,
            mode=request.mode,
        )
        options = _adapter_options(
            request=request,
            capabilities=adapter.capabilities,
            query_count=len(effective_queries),
        )

        result_batches = [
            adapter.search(query=query, options=options)
            for query in effective_queries
        ]
        return GatewaySearchResponse(
            results=_merge_ranked_results(
                result_batches,
                max_results=request.max_results,
            )
        )

    def _adapter_for_request(self, request: GatewaySearchRequest) -> SearchAdapter:
        channel = _normalize_channel(request.channel or self._default_channel)
        adapter = self._adapters.get(channel)
        if adapter is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Unsupported search channel: {channel}",
            )
        return adapter


def _adapter_options(
    *,
    request: GatewaySearchRequest,
    capabilities: SearchAdapterCapabilities,
    query_count: int,
) -> SearchAdapterOptions:
    include_raw_content = _should_include_raw_content(
        request.mode,
        capabilities=capabilities,
    )
    return SearchAdapterOptions(
        mode=request.mode,
        search_depth=_search_depth_for_mode(
            request.mode,
            capabilities=capabilities,
        ),
        max_results=_max_results_per_query(
            request=request,
            query_count=query_count,
        ),
        include_raw_content=include_raw_content,
        raw_content_max_chars=(
            _raw_content_max_chars_for_mode(request.mode)
            if include_raw_content
            else None
        ),
        locale=request.locale,
    )


def _search_depth_for_mode(
    mode: SearchMode,
    *,
    capabilities: SearchAdapterCapabilities,
) -> SearchDepth:
    if mode in {SearchMode.MEDIUM, SearchMode.DEEP}:
        if capabilities.supports_advanced_search:
            return "advanced"
    return "basic"


def _should_include_raw_content(
    mode: SearchMode,
    *,
    capabilities: SearchAdapterCapabilities,
) -> bool:
    return mode in {SearchMode.MEDIUM, SearchMode.DEEP} and (
        capabilities.supports_raw_content
    )


def _raw_content_max_chars_for_mode(mode: SearchMode) -> int | None:
    if mode is SearchMode.MEDIUM:
        return MEDIUM_RAW_CONTENT_SNIPPET_MAX_CHARS
    if mode is SearchMode.DEEP:
        return DEEP_RAW_CONTENT_SNIPPET_MAX_CHARS
    return None


def _max_results_per_query(
    *,
    request: GatewaySearchRequest,
    query_count: int,
) -> int:
    if request.mode is SearchMode.LITE or query_count <= 1:
        return request.max_results
    target = max(3, request.max_results // min(query_count, 4))
    return min(request.max_results, target)


def _merge_ranked_results(
    result_batches: list[list[GatewaySearchResult]],
    *,
    max_results: int,
) -> list[GatewaySearchResult]:
    results: list[GatewaySearchResult] = []
    seen_urls: set[str] = set()
    for batch in result_batches:
        for result in batch:
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            results.append(result)
            if len(results) >= max_results:
                return results
    return results


def _normalize_channel(value: str) -> str:
    return value.strip().lower()
