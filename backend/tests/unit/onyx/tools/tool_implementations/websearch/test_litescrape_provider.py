import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from requests import HTTPError

from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.tools.tool_implementations.web_search.models import DEFAULT_MAX_RESULTS
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
    provider_requires_api_key,
)
from shared_configs.enums import WebSearchProviderType


@pytest.mark.parametrize(
    "provider_type, search_url, supports_contents",
    [
        (WebSearchProviderType.SERPER, "https://google.serper.dev/search", True),
        (WebSearchProviderType.LITESCRAPE, "https://api.litescrape.com/search", False),
    ],
)
@pytest.mark.parametrize("config", [None, {"num_results": "7"}])
def test_serper_compatible_search(
    provider_type: WebSearchProviderType,
    search_url: str,
    supports_contents: bool,
    config: dict[str, str] | None,
) -> None:
    provider = build_search_provider_from_config(provider_type, "test-api-key", config)
    assert isinstance(provider, WebContentProvider) is supports_contents
    with patch("requests.post") as post:
        post.return_value.json.return_value = {
            "organic": [
                {
                    "title": " Example ",
                    "link": " https://example.com/page ",
                    "snippet": " Text ",
                },
                {"link": " "},
            ]
        }
        results = provider.search("café & tea")
        assert [(r.title, r.link, r.snippet) for r in results] == [
            ("Example", "https://example.com/page", "Text")
        ]
        post.assert_called_once_with(
            search_url,
            headers={"X-API-KEY": "test-api-key", "Content-Type": "application/json"},
            data=json.dumps(
                {
                    "q": "café & tea",
                    "num": int(config["num_results"]) if config else DEFAULT_MAX_RESULTS,
                }
            ),
            timeout=60,
        )
        post.return_value.raise_for_status.assert_called_once()
        assert provider.test_connection() == {"status": "ok"}


@pytest.mark.parametrize("api_key", [None, ""])
def test_litescrape_requires_api_key(api_key: str | None) -> None:
    assert provider_requires_api_key(WebSearchProviderType.LITESCRAPE)
    with pytest.raises(ValueError, match="API key is required for litescrape"):
        build_search_provider_from_config(WebSearchProviderType.LITESCRAPE, api_key, None)


@pytest.mark.parametrize(
    "error, expected",
    [
        ("Invalid API key", "Invalid Litescrape API key"),
        ("Service unavailable", "Litescrape API key validation failed"),
    ],
)
def test_litescrape_connection_error_names_provider(error: str, expected: str) -> None:
    provider = build_search_provider_from_config(
        WebSearchProviderType.LITESCRAPE, "test-api-key", None
    )
    with patch.object(provider, "search", side_effect=HTTPError(error)):
        with pytest.raises(HTTPException, match=expected):
            provider.test_connection()


def test_litescrape_connection_rejects_empty_results() -> None:
    provider = build_search_provider_from_config(
        WebSearchProviderType.LITESCRAPE, "test-api-key", None
    )
    with patch("requests.post") as post:
        post.return_value.json.return_value = {"organic": []}
        assert provider.search("test") == []
        with pytest.raises(HTTPException, match="search returned no results"):
            provider.test_connection()
