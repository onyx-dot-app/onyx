from __future__ import annotations

import json
from typing import Any

import httpx

from onyx.search_gateway.models import GatewaySearchRequest
from onyx.search_gateway.models import SearchMode
from onyx.search_gateway.tavily import TavilySearchClient


def test_lite_search_maps_to_tavily_basic_payload_and_normalizes_results() -> None:
    captured_requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "json": request.read().decode("utf-8"),
            }
        )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Gold Futures Price Today",
                        "url": "https://example.com/gold",
                        "content": "Gold futures moved higher today.",
                        "published_date": "2026-06-15",
                    }
                ]
            },
        )

    client = TavilySearchClient(
        api_key="tavily-key",
        api_url="https://api.tavily.test/search",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.search(
        GatewaySearchRequest(
            queries=["  gold price today  "],
            mode=SearchMode.LITE,
            channel="tavily",
            max_results=5,
            locale="zh-CN",
        )
    )

    assert len(captured_requests) == 1
    assert captured_requests[0]["url"] == "https://api.tavily.test/search"
    assert captured_requests[0]["headers"]["authorization"] == "Bearer tavily-key"
    assert '"query":"gold price today"' in captured_requests[0]["json"]
    assert '"search_depth":"basic"' in captured_requests[0]["json"]
    assert '"max_results":5' in captured_requests[0]["json"]
    assert '"include_raw_content":false' in captured_requests[0]["json"]
    assert response.results[0].title == "Gold Futures Price Today"
    assert response.results[0].url == "https://example.com/gold"
    assert response.results[0].snippet == "Gold futures moved higher today."
    assert response.results[0].published_date == "2026-06-15"


def test_deep_search_fans_out_queries_requests_raw_content_and_dedupes_urls() -> None:
    captured_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Same Result",
                        "url": "https://example.com/shared",
                        "content": "Shared result",
                    }
                ]
            },
        )

    client = TavilySearchClient(
        api_key="tavily-key",
        api_url="https://api.tavily.test/search",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.search(
        GatewaySearchRequest(
            queries=["swc-project / swc"],
            mode=SearchMode.DEEP,
            channel="tavily",
            max_results=10,
            locale="zh-CN",
        )
    )

    assert len(captured_payloads) > 1
    assert captured_payloads[0]["query"] == "swc-project / swc"
    captured_queries = [payload["query"] for payload in captured_payloads]
    assert any("GitHub" in query for query in captured_queries)
    assert any("official documentation" in query for query in captured_queries)
    assert all(payload["search_depth"] == "advanced" for payload in captured_payloads)
    assert all(payload["include_raw_content"] is True for payload in captured_payloads)
    assert [result.url for result in response.results] == ["https://example.com/shared"]


def test_medium_search_uses_limited_fanout_advanced_search_and_raw_content() -> None:
    captured_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "SWC Docs",
                        "url": f"https://example.com/{len(captured_payloads)}",
                        "content": "Short snippet.",
                        "raw_content": "Medium evidence sentence. " * 80,
                    }
                ]
            },
        )

    client = TavilySearchClient(
        api_key="tavily-key",
        api_url="https://api.tavily.test/search",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.search(
        GatewaySearchRequest(
            queries=["swc-project / swc"],
            mode=SearchMode.MEDIUM,
            channel="tavily",
            max_results=10,
            locale="zh-CN",
        )
    )

    assert 3 <= len(captured_payloads) <= 5
    captured_queries = [payload["query"] for payload in captured_payloads]
    assert captured_queries[0] == "swc-project / swc"
    assert any("official documentation" in query for query in captured_queries)
    assert any("GitHub" in query for query in captured_queries)
    assert all(payload["search_depth"] == "advanced" for payload in captured_payloads)
    assert all(payload["include_raw_content"] is True for payload in captured_payloads)
    assert response.results[0].snippet.startswith("Medium evidence sentence.")
    assert len(response.results[0].snippet) <= 800


def test_deep_search_prefers_truncated_raw_content_for_snippet() -> None:
    long_raw_content = "Deep evidence sentence. " * 100

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "SWC Docs",
                        "url": "https://swc.rs/docs",
                        "content": "Short search snippet.",
                        "raw_content": long_raw_content,
                    }
                ]
            },
        )

    client = TavilySearchClient(
        api_key="tavily-key",
        api_url="https://api.tavily.test/search",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.search(
        GatewaySearchRequest(
            queries=["swc-project / swc"],
            mode=SearchMode.DEEP,
            channel="tavily",
            max_results=1,
            locale="zh-CN",
        )
    )

    assert response.results[0].snippet.startswith("Deep evidence sentence.")
    assert response.results[0].snippet != "Short search snippet."
    assert len(response.results[0].snippet) <= 1200


def test_deep_per_query_max_results_never_exceeds_request_max_results() -> None:
    captured_payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.com/result",
                        "content": "Snippet",
                    }
                ]
            },
        )

    client = TavilySearchClient(
        api_key="tavily-key",
        api_url="https://api.tavily.test/search",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.search(
        GatewaySearchRequest(
            queries=["swc-project / swc"],
            mode=SearchMode.DEEP,
            channel="tavily",
            max_results=1,
            locale="zh-CN",
        )
    )

    assert captured_payloads[0]["max_results"] == 1


def test_tavily_rate_limit_maps_to_standard_rate_limited_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": "too many requests"})

    client = TavilySearchClient(
        api_key="tavily-key",
        api_url="https://api.tavily.test/search",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    try:
        client.search(
            GatewaySearchRequest(
                queries=["gold"],
                mode=SearchMode.LITE,
                channel="tavily",
                max_results=5,
                locale="zh-CN",
            )
        )
    except Exception as exc:
        assert exc.__class__.__name__ == "OnyxError"
        assert getattr(exc, "error_code").code == "RATE_LIMITED"
    else:
        raise AssertionError("Expected Tavily 429 to raise OnyxError")
