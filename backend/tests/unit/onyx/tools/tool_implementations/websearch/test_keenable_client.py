from typing import Any
from unittest.mock import MagicMock, patch

from onyx.tools.tool_implementations.web_search.clients.keenable_client import (
    KEENABLE_MAX_SNIPPET_CHARS,
    KeenableClient,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
    provider_requires_api_key,
)
from shared_configs.enums import WebSearchProviderType


def _response(results: list[dict[str, Any]]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"results": results}
    response.raise_for_status.return_value = None
    return response


@patch(
    "onyx.tools.tool_implementations.web_search.clients.keenable_client.requests.post"
)
def test_search_reads_the_snippet_field(mock_post: MagicMock) -> None:
    """Keenable returns both fields and `description` is frequently empty."""
    mock_post.return_value = _response(
        [
            {
                "url": "https://example.com/one",
                "title": "One",
                "description": "",
                "snippet": "First page text",
            }
        ]
    )

    results = KeenableClient().search("test query")

    assert len(results) == 1
    assert results[0].snippet == "First page text"


@patch(
    "onyx.tools.tool_implementations.web_search.clients.keenable_client.requests.post"
)
def test_search_falls_back_to_description(mock_post: MagicMock) -> None:
    mock_post.return_value = _response(
        [
            {
                "url": "https://example.com/one",
                "title": "One",
                "description": "A description",
            }
        ]
    )

    results = KeenableClient().search("test query")

    assert results[0].snippet == "A description"


@patch(
    "onyx.tools.tool_implementations.web_search.clients.keenable_client.requests.post"
)
def test_search_collapses_whitespace_and_caps_the_snippet(mock_post: MagicMock) -> None:
    """Snippets are raw page text: newlines in them, and far longer than a snippet."""
    mock_post.return_value = _response(
        [
            {
                "url": "https://example.com/one",
                "title": "One",
                "description": "",
                "snippet": "line one\n\nline two" + " padding" * 500,
            }
        ]
    )

    snippet = KeenableClient().search("test query")[0].snippet

    assert len(snippet) == KEENABLE_MAX_SNIPPET_CHARS
    assert "\n" not in snippet
    assert snippet.startswith("line one line two")


@patch(
    "onyx.tools.tool_implementations.web_search.clients.keenable_client.requests.post"
)
def test_search_skips_results_without_a_link(mock_post: MagicMock) -> None:
    mock_post.return_value = _response(
        [
            {"title": "No URL", "snippet": "text"},
            {"url": "https://example.com/one", "title": "One", "snippet": "text"},
        ]
    )

    results = KeenableClient().search("test query")

    assert [result.link for result in results] == ["https://example.com/one"]


def test_keenable_does_not_require_an_api_key() -> None:
    assert provider_requires_api_key(WebSearchProviderType.KEENABLE) is False


def test_build_keenable_provider_without_api_key() -> None:
    """With no key and no config, Keenable builds against the public endpoint."""
    provider = build_search_provider_from_config(
        provider_type=WebSearchProviderType.KEENABLE,
        api_key=None,
        config={},
    )

    assert isinstance(provider, KeenableClient)
