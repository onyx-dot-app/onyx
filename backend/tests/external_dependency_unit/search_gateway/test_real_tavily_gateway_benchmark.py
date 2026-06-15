from __future__ import annotations

import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from onyx.search_gateway.config import DEFAULT_TAVILY_API_URL
from onyx.search_gateway.config import SearchGatewayConfig
from onyx.search_gateway.server import create_app
from onyx.tools.tool_implementations.open_url.models import FailedFetch
from onyx.tools.tool_implementations.open_url.open_url_tool import (
    _build_search_snippet_fallback_sections,
)

_TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "").strip()
_RUN_REAL_BENCHMARK = (
    os.environ.get("GLOMI_RUN_REAL_SEARCH_BENCHMARK", "").strip().lower() == "true"
)
_GATEWAY_API_KEY = "benchmark-gateway-key"

pytestmark = pytest.mark.skipif(
    not _RUN_REAL_BENCHMARK or not _TAVILY_API_KEY,
    reason=(
        "Set GLOMI_RUN_REAL_SEARCH_BENCHMARK=true and TAVILY_API_KEY to run "
        "the real Glomi Search Gateway benchmark."
    ),
)


def _benchmark_client() -> TestClient:
    app = create_app(
        config=SearchGatewayConfig(
            gateway_api_key=_GATEWAY_API_KEY,
            tavily_api_key=_TAVILY_API_KEY,
            tavily_api_url=os.environ.get(
                "GLOMI_SEARCH_GATEWAY_TAVILY_API_URL",
                DEFAULT_TAVILY_API_URL,
            ),
            timeout_seconds=int(
                os.environ.get("GLOMI_SEARCH_GATEWAY_TIMEOUT_SECONDS", "15")
            ),
            default_channel="tavily",
        )
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("mode", "query"),
    [
        (
            "medium",
            "SWC project JavaScript compiler architecture official documentation GitHub",
        ),
        (
            "deep",
            "today gold price trend macro drivers forecast support resistance",
        ),
    ],
)
def test_real_gateway_results_are_open_url_fallback_ready(
    mode: str,
    query: str,
) -> None:
    response = _benchmark_client().post(
        "/search",
        headers={"Authorization": f"Bearer {_GATEWAY_API_KEY}"},
        json={
            "queries": [query],
            "mode": mode,
            "channel": "tavily",
            "max_results": 8,
            "locale": "zh-CN",
        },
    )

    assert response.status_code == 200, response.text
    results: list[dict[str, Any]] = response.json()["results"]
    assert results
    assert all(result.get("url") for result in results)

    fallback_ready = [
        result
        for result in results
        if isinstance(result.get("snippet"), str)
        and len(result["snippet"].strip()) >= 80
    ]
    assert fallback_ready, results

    first = fallback_ready[0]
    url = first["url"]
    snippet = first["snippet"]
    sections, failures = _build_search_snippet_fallback_sections(
        urls=[url],
        existing_sections=[],
        failed_web_fetches=[
            FailedFetch(url=url, failure_reason="benchmark simulated crawl failure")
        ],
        url_snippet_map={url: snippet},
    )

    assert failures == []
    assert len(sections) == 1
    assert snippet[:80] in sections[0].combined_content
