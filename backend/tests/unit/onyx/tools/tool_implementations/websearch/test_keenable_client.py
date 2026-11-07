from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

import onyx.tools.tool_implementations.web_search.clients.keenable_client as keenable_module
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.tools.tool_implementations.web_search.clients.keenable_client import (
    KEENABLE_MAX_SNIPPET_CHARS,
    KeenableClient,
)
from onyx.tools.tool_implementations.web_search.models import WebSearchResult
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
    provider_requires_api_key,
)
from shared_configs.enums import WebSearchProviderType


def _response(results: list[dict[str, Any]]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
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


@pytest.mark.parametrize(
    ("error_msg", "expected"),
    [
        (
            "Keenable search failed (status 401): Invalid API key",
            "Invalid Keenable API key",
        ),
        (
            "Keenable search failed (status 402): Payment Required",
            "insufficient credits",
        ),
        (
            "Keenable search failed (status 429): Too many requests",
            "rate limit exceeded",
        ),
        ("Keenable search failed (status 400): Bad request", "validation failed"),
    ],
)
def test_test_connection_raises_onyx_error(
    monkeypatch: pytest.MonkeyPatch, error_msg: str, expected: str
) -> None:
    client = KeenableClient(api_key="test-key")

    def _mock_search(query: str) -> list[WebSearchResult]:  # noqa: ARG001
        raise ValueError(error_msg)

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(OnyxError, match=expected) as exc_info:
        client.test_connection()

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_test_connection_fails_on_empty_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KeenableClient()

    def _mock_search(query: str) -> list[WebSearchResult]:  # noqa: ARG001
        return []

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(OnyxError, match="returned no results"):
        client.test_connection()


def test_test_connection_propagates_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = KeenableClient()

    def _mock_search(query: str) -> list[WebSearchResult]:  # noqa: ARG001
        raise RuntimeError("unexpected parsing bug")

    monkeypatch.setattr(client, "search", _mock_search)

    with pytest.raises(RuntimeError, match="unexpected parsing bug"):
        client.test_connection()


@pytest.mark.parametrize(
    "private_url",
    ["http://127.0.0.1:8080", "https://169.254.169.254", "https://10.0.0.5"],
)
def test_search_blocks_private_base_url_on_cloud(
    monkeypatch: pytest.MonkeyPatch, private_url: str
) -> None:
    monkeypatch.setattr(keenable_module, "MULTI_TENANT", True)
    post_calls: list[str] = []
    monkeypatch.setattr(
        keenable_module.requests,
        "post",
        lambda url, **_kwargs: post_calls.append(url),
    )
    client = KeenableClient(api_key="test-key", base_url=private_url)

    with pytest.raises(ValueError, match="base_url is not allowed"):
        client.search("onyx")

    assert post_calls == []


def test_search_rejects_redirect_without_following(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_kwargs: list[dict[str, Any]] = []

    def _mock_post(_url: str, **kwargs: Any) -> requests.Response:
        post_kwargs.append(kwargs)
        response = requests.Response()
        response.status_code = 307
        response.headers["Location"] = "http://169.254.169.254/latest"
        return response

    monkeypatch.setattr(keenable_module.requests, "post", _mock_post)
    client = KeenableClient(api_key="test-key")

    with pytest.raises(ValueError, match="returned a redirect"):
        client.search("onyx")

    assert len(post_kwargs) == 1
    assert post_kwargs[0]["allow_redirects"] is False


def test_build_keenable_provider_reads_base_url() -> None:
    provider = build_search_provider_from_config(
        provider_type=WebSearchProviderType.KEENABLE,
        api_key=None,
        config={"base_url": "https://keenable.example.com/"},
    )

    assert isinstance(provider, KeenableClient)
    assert provider._base_url == "https://keenable.example.com"
