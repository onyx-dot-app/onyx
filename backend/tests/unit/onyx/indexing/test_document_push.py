"""Unit tests for the config-driven document push (non-EE)."""

from collections.abc import Iterator
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from onyx.indexing.document_push import DocumentPushPayload
from onyx.indexing.document_push import get_document_push_config
from onyx.indexing.document_push import push_document_via_config

_MODULE = "onyx.indexing.document_push"


def _make_payload(doc_id: str = "doc1") -> DocumentPushPayload:
    return DocumentPushPayload(
        document_id=doc_id,
        title="Title",
        content="Hello",
        source="web",
        url="https://source.example.com/doc",
        doc_updated_at=None,
        metadata={},
    )


def _setup_client(
    mock_client_cls: MagicMock,
    *,
    status_code: int = 200,
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {}
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            str(status_code),
            request=MagicMock(),
            response=MagicMock(status_code=status_code, text="error"),
        )
    mock_client = MagicMock()
    mock_client.post = MagicMock(return_value=response)
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
    return mock_client


@pytest.fixture(autouse=True)
def _clear_config_cache() -> Iterator[None]:
    get_document_push_config.cache_clear()
    yield
    get_document_push_config.cache_clear()


def test_noop_when_unconfigured() -> None:
    with (
        patch(f"{_MODULE}.DOCUMENT_PUSH_ENDPOINT_URL", None),
        patch("httpx.Client") as mock_client_cls,
    ):
        push_document_via_config(_make_payload())
    mock_client_cls.assert_not_called()


def test_push_posts_payload_with_bearer_auth() -> None:
    with (
        patch(f"{_MODULE}.DOCUMENT_PUSH_ENDPOINT_URL", "https://push.example.com/docs"),
        patch(f"{_MODULE}.DOCUMENT_PUSH_API_KEY", "secret-key"),
        patch("httpx.Client") as mock_client_cls,
    ):
        mock_client = _setup_client(mock_client_cls)
        push_document_via_config(_make_payload())

    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0] == "https://push.example.com/docs"
    assert kwargs["json"]["document_id"] == "doc1"
    assert kwargs["json"]["content"] == "Hello"
    assert kwargs["headers"]["Authorization"] == "Bearer secret-key"


def test_push_failure_does_not_raise() -> None:
    with (
        patch(f"{_MODULE}.DOCUMENT_PUSH_ENDPOINT_URL", "https://push.example.com/docs"),
        patch("httpx.Client") as mock_client_cls,
    ):
        _setup_client(mock_client_cls, status_code=500)
        # SOFT fail strategy — a failing endpoint must not fail indexing.
        push_document_via_config(_make_payload())


def test_invalid_url_disables_push() -> None:
    with (
        patch(f"{_MODULE}.DOCUMENT_PUSH_ENDPOINT_URL", "ftp://push.example.com/docs"),
        patch("httpx.Client") as mock_client_cls,
    ):
        assert get_document_push_config() is None
        push_document_via_config(_make_payload())
    mock_client_cls.assert_not_called()


def test_non_positive_timeout_disables_push() -> None:
    with (
        patch(f"{_MODULE}.DOCUMENT_PUSH_ENDPOINT_URL", "https://push.example.com/docs"),
        patch(f"{_MODULE}.DOCUMENT_PUSH_TIMEOUT_SECONDS", 0.0),
        patch("httpx.Client") as mock_client_cls,
    ):
        assert get_document_push_config() is None
        push_document_via_config(_make_payload())
    mock_client_cls.assert_not_called()


def test_private_network_url_is_allowed() -> None:
    # Operator-supplied env config may target internal systems — the primary
    # self-hosted use case.
    with patch(
        f"{_MODULE}.DOCUMENT_PUSH_ENDPOINT_URL", "http://192.168.1.10:8080/push"
    ):
        config = get_document_push_config()
    assert config is not None
    assert config.endpoint_url == "http://192.168.1.10:8080/push"
