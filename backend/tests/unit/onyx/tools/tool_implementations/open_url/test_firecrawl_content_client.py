from __future__ import annotations

from typing import Any

import pytest
import requests

import onyx.tools.tool_implementations.open_url.firecrawl as firecrawl_module
from onyx.tools.tool_implementations.open_url.firecrawl import FirecrawlClient


def test_contents_blocks_private_base_url_on_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(firecrawl_module, "MULTI_TENANT", True)
    post_calls: list[str] = []
    monkeypatch.setattr(
        firecrawl_module.requests,
        "post",
        lambda url, **_kwargs: post_calls.append(url),
    )
    client = FirecrawlClient(
        api_key="fc-key", base_url="http://169.254.169.254/v2/scrape"
    )

    results = client.contents(["https://example.com"])

    assert post_calls == []
    assert results[0].scrape_successful is False
    assert client.last_error is not None


def test_contents_does_not_follow_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    post_kwargs: list[dict[str, Any]] = []

    def _mock_post(_url: str, **kwargs: Any) -> requests.Response:
        post_kwargs.append(kwargs)
        response = requests.Response()
        response.status_code = 307
        response.headers["Location"] = "http://169.254.169.254/latest"
        response._content = b""
        return response

    monkeypatch.setattr(firecrawl_module.requests, "post", _mock_post)
    client = FirecrawlClient(api_key="fc-key")

    results = client.contents(["https://example.com"])

    assert len(post_kwargs) == 1
    assert post_kwargs[0]["allow_redirects"] is False
    assert results[0].scrape_successful is False
