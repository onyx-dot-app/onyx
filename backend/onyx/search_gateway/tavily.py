from __future__ import annotations

from typing import Any

import httpx

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.search_gateway.adapters import SearchAdapterCapabilities
from onyx.search_gateway.adapters import SearchAdapterOptions
from onyx.search_gateway.models import GatewaySearchRequest
from onyx.search_gateway.models import GatewaySearchResponse
from onyx.search_gateway.models import GatewaySearchResult
from onyx.search_gateway.service import SearchGatewayService


class TavilySearchAdapter:
    def __init__(
        self,
        *,
        api_key: str,
        api_url: str,
        timeout_seconds: int = 15,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._http_client = http_client or httpx.Client(timeout=timeout_seconds)
        self._capabilities = SearchAdapterCapabilities(
            channel="tavily",
            supports_advanced_search=True,
            supports_raw_content=True,
            supports_extract=True,
        )

    @property
    def capabilities(self) -> SearchAdapterCapabilities:
        return self._capabilities

    def search(
        self,
        *,
        query: str,
        options: SearchAdapterOptions,
    ) -> list[GatewaySearchResult]:
        try:
            response = self._http_client.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "query": query,
                    "search_depth": options.search_depth,
                    "max_results": options.max_results,
                    "include_answer": False,
                    "include_images": False,
                    "include_raw_content": options.include_raw_content,
                },
            )
        except httpx.TimeoutException as exc:
            raise OnyxError(
                OnyxErrorCode.GATEWAY_TIMEOUT,
                "Tavily search timed out.",
            ) from exc
        except httpx.HTTPError as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Tavily search request failed.",
            ) from exc

        if response.status_code == 429:
            raise OnyxError(
                OnyxErrorCode.RATE_LIMITED,
                "Tavily rate limit exceeded.",
            )
        if response.status_code in {401, 403}:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Tavily rejected the configured API key.",
            )
        if response.is_error:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                f"Tavily search failed: {_extract_error_detail(response)}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Tavily search returned a non-JSON response.",
            ) from exc

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Tavily search response did not include a results list.",
            )

        return [
            result
            for raw_result in raw_results
            if (
                result := _normalize_tavily_result(
                    raw_result,
                    raw_content_max_chars=options.raw_content_max_chars,
                )
            )
            is not None
        ]


class TavilySearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_url: str,
        timeout_seconds: int = 15,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._service = SearchGatewayService(
            adapters=[
                TavilySearchAdapter(
                    api_key=api_key,
                    api_url=api_url,
                    timeout_seconds=timeout_seconds,
                    http_client=http_client,
                )
            ],
            default_channel="tavily",
        )

    def search(self, request: GatewaySearchRequest) -> GatewaySearchResponse:
        return self._service.search(request)


def _normalize_tavily_result(
    raw_result: Any,
    *,
    raw_content_max_chars: int | None,
) -> GatewaySearchResult | None:
    if not isinstance(raw_result, dict):
        return None

    url = _clean_string(raw_result.get("url"))
    if not url:
        return None

    title = _clean_string(raw_result.get("title")) or url
    snippet = _normalize_snippet(
        raw_result,
        raw_content_max_chars=raw_content_max_chars,
    )

    return GatewaySearchResult(
        title=title,
        url=url,
        snippet=snippet,
        author=_optional_clean_string(raw_result.get("author")),
        published_date=_optional_clean_string(raw_result.get("published_date")),
    )


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except ValueError:
        return response.text.strip()[:200] or "No error details"

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()[:200]

    return str(payload)[:200]


def _clean_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_clean_string(value: Any) -> str | None:
    cleaned = _clean_string(value)
    return cleaned or None


def _normalize_snippet(
    raw_result: dict[str, Any],
    *,
    raw_content_max_chars: int | None,
) -> str:
    raw_content = _clean_string(raw_result.get("raw_content"))
    if raw_content_max_chars is not None and raw_content:
        return _truncate_snippet(raw_content, max_chars=raw_content_max_chars)

    return (
        _clean_string(raw_result.get("content"))
        or _clean_string(raw_result.get("snippet"))
        or _truncate_snippet(
            raw_content,
            max_chars=1200,
        )
    )


def _truncate_snippet(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip()
