from __future__ import annotations

from onyx.error_handling.exceptions import OnyxError
from onyx.search_gateway.adapters import SearchAdapterCapabilities
from onyx.search_gateway.adapters import SearchAdapterOptions
from onyx.search_gateway.models import GatewaySearchRequest
from onyx.search_gateway.models import GatewaySearchResult
from onyx.search_gateway.models import SearchMode
from onyx.search_gateway.service import SearchGatewayService


class RecordingAdapter:
    def __init__(
        self,
        *,
        channel: str,
        supports_advanced_search: bool = True,
        supports_raw_content: bool = True,
    ) -> None:
        self.capabilities = SearchAdapterCapabilities(
            channel=channel,
            supports_advanced_search=supports_advanced_search,
            supports_raw_content=supports_raw_content,
        )
        self.calls: list[tuple[str, SearchAdapterOptions]] = []

    def search(
        self,
        *,
        query: str,
        options: SearchAdapterOptions,
    ) -> list[GatewaySearchResult]:
        self.calls.append((query, options))
        return [
            GatewaySearchResult(
                title=query,
                url=f"https://example.com/{len(self.calls)}",
                snippet=f"snippet for {query}",
            )
        ]


def test_service_routes_to_default_adapter_and_applies_medium_planning() -> None:
    adapter = RecordingAdapter(channel="fake")
    service = SearchGatewayService(
        adapters=[adapter],
        default_channel="fake",
    )

    response = service.search(
        GatewaySearchRequest(
            queries=["swc-project / swc"],
            mode=SearchMode.MEDIUM,
            max_results=10,
        )
    )

    called_queries = [query for query, _options in adapter.calls]
    assert 3 <= len(called_queries) <= 5
    assert called_queries[0] == "swc-project / swc"
    assert any("official documentation" in query for query in called_queries)
    assert all(options.search_depth == "advanced" for _query, options in adapter.calls)
    assert all(options.include_raw_content for _query, options in adapter.calls)
    assert all(options.raw_content_max_chars == 800 for _query, options in adapter.calls)
    assert len(response.results) == len(called_queries)


def test_service_degrades_raw_content_when_adapter_does_not_support_it() -> None:
    adapter = RecordingAdapter(
        channel="basic-only",
        supports_advanced_search=False,
        supports_raw_content=False,
    )
    service = SearchGatewayService(
        adapters=[adapter],
        default_channel="basic-only",
    )

    service.search(
        GatewaySearchRequest(
            queries=["gold price today"],
            mode=SearchMode.DEEP,
            max_results=5,
        )
    )

    assert adapter.calls
    assert all(options.search_depth == "basic" for _query, options in adapter.calls)
    assert all(not options.include_raw_content for _query, options in adapter.calls)
    assert all(options.raw_content_max_chars is None for _query, options in adapter.calls)


def test_service_dedupes_urls_across_adapter_calls() -> None:
    class DuplicateAdapter(RecordingAdapter):
        def search(
            self,
            *,
            query: str,
            options: SearchAdapterOptions,
        ) -> list[GatewaySearchResult]:
            self.calls.append((query, options))
            return [
                GatewaySearchResult(
                    title=query,
                    url="https://example.com/shared",
                    snippet="shared",
                )
            ]

    adapter = DuplicateAdapter(channel="fake")
    service = SearchGatewayService(adapters=[adapter], default_channel="fake")

    response = service.search(
        GatewaySearchRequest(
            queries=["swc-project / swc"],
            mode=SearchMode.DEEP,
            max_results=10,
        )
    )

    assert len(adapter.calls) > 1
    assert [result.url for result in response.results] == ["https://example.com/shared"]


def test_service_rejects_unknown_channel() -> None:
    service = SearchGatewayService(
        adapters=[RecordingAdapter(channel="fake")],
        default_channel="fake",
    )

    try:
        service.search(
            GatewaySearchRequest(
                queries=["gold"],
                mode=SearchMode.LITE,
                channel="missing",
            )
        )
    except OnyxError as exc:
        assert exc.error_code.code == "INVALID_INPUT"
        assert "Unsupported search channel: missing" in exc.detail
    else:
        raise AssertionError("Expected unknown channel to raise OnyxError")
