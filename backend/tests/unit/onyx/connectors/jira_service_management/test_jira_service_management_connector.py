"""Unit tests for the Jira Service Management connector (offline, no network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
import requests

from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
    validate_project_key,
)
from onyx.connectors.jira_service_management.jira_service_management_connector import (
    JiraServiceManagementConnector,
    _validate_base_url,
)
from onyx.connectors.models import SlimDocument
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface


class HB(IndexingHeartbeatInterface):
    """Minimal heartbeat implementing the real interface contract."""

    def __init__(self, stop: bool = False) -> None:
        """Initialize mock heartbeat with stop state and tracking calls."""
        super().__init__()
        self._stop = stop
        self.calls: list[tuple[str, int]] = []

    def should_stop(self) -> bool:
        """Return True if indexing stop was requested."""
        return self._stop

    def progress(self, tag: str, amount: int) -> None:
        """Record a progress callback event."""
        self.calls.append((tag, amount))


def _connector(
    request_jql: str | None = None,
    batch_size: int = 10,
    base_url: str = "https://acme.atlassian.net",
) -> JiraServiceManagementConnector:
    """Instantiate a JiraServiceManagementConnector for testing."""
    return JiraServiceManagementConnector(
        base_url=base_url,
        project_key="ABC",
        batch_size=batch_size,
        request_jql=request_jql,
    )


def _issue(key: str) -> dict[str, Any]:
    """Generate a sample Jira Cloud issue dictionary."""
    return {
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Desc"}],
                    }
                ],
            },
            "status": {"name": "Open"},
            "priority": {"name": "High"},
            "created": "2026-01-01T00:00:00.000+0000",
            "updated": "2026-01-02T00:00:00.000+0000",
        },
    }


def _stub_search(pages: list[dict[str, Any]]) -> Any:
    it = iter(pages)

    def _search(self: Any, jql: str, token: str | None = None) -> dict[str, Any]:  # noqa: ARG001
        _search.last_jql = jql
        try:
            return next(it)
        except StopIteration:
            return {"issues": []}

    _search.last_jql = None  # type: ignore[attr-defined]
    return _search


# ------------------------------------------------------------------ security
def test_http_non_loopback_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS is required"):
        _validate_base_url("http://acme.atlassian.net")


def test_http_subdomain_trick_rejected() -> None:
    with pytest.raises(ValueError, match="HTTPS is required"):
        _validate_base_url("http://127.evil.com")


def test_http_loopback_allowed() -> None:
    assert _validate_base_url("http://localhost:2990") == "http://localhost:2990"
    assert _validate_base_url("http://127.0.0.1") == "http://127.0.0.1"
    assert _validate_base_url("http://[::1]:8080") == "http://[::1]:8080"


def test_base_url_with_userinfo_rejected() -> None:
    """Verify base_url with embedded user credentials is rejected."""
    with pytest.raises(ValueError, match="embedded credentials"):
        _validate_base_url("https://user:pass@acme.atlassian.net")


def test_https_allowed_and_trailing_slash_stripped() -> None:
    assert _validate_base_url("https://acme.atlassian.net/") == (
        "https://acme.atlassian.net"
    )


def test_connector_ctor_enforces_https() -> None:
    with pytest.raises(ValueError, match="HTTPS is required"):
        JiraServiceManagementConnector(
            base_url="http://acme.atlassian.net", project_key="ABC"
        )


# ---------------------------------------------------------------- scope/jql
def test_request_jql_propagated_and_scoped() -> None:
    c = _connector(request_jql="status = Open OR status = Closed")
    assert 'project = "ABC"' in c.request_jql
    # user clause parenthesised so OR cannot escape the project scope
    assert c.request_jql == ('project = "ABC" AND (status = Open OR status = Closed)')


def test_no_request_jql_shows_project_only() -> None:
    c = _connector()
    assert c.request_jql == 'project = "ABC"'


def test_project_key_validated() -> None:
    with pytest.raises(ValueError):
        JiraServiceManagementConnector(
            base_url="https://x.atlassian.net", project_key='ABC" OR 1=1'
        )


def test_project_key_trailing_newline_rejected() -> None:
    with pytest.raises(ValueError):
        validate_project_key("ABC\n")


def test_request_jql_order_by_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported clause: ORDER BY"):
        JiraServiceManagementConnectorConfig(
            base_url="https://acme.atlassian.net",
            project_key="ABC",
            request_jql="status = Open ORDER BY created DESC",
        )


def test_request_jql_unbalanced_parentheses_rejected() -> None:
    with pytest.raises(ValueError, match="unbalanced parentheses"):
        JiraServiceManagementConnectorConfig(
            base_url="https://acme.atlassian.net",
            project_key="ABC",
            request_jql="status = Open) OR project = OTHER OR (status = Open",
        )


# -------------------------------------------------------------- pagination
def test_pagination_follows_cursor() -> None:
    pages = [
        {"issues": [_issue("ABC-1"), _issue("ABC-2")], "nextPageToken": "t1"},
        {"issues": [_issue("ABC-3")]},
    ]
    stub = _stub_search(pages)
    c = _connector(batch_size=1)
    c._search = stub.__get__(c, type(c))  # type: ignore[method-assign]
    c._get_comments = MagicMock(return_value=[])  # type: ignore[method-assign]
    ids = [d.id for batch in c.load_from_state() for d in batch]
    assert ids == [
        "https://acme.atlassian.net/browse/ABC-1",
        "https://acme.atlassian.net/browse/ABC-2",
        "https://acme.atlassian.net/browse/ABC-3",
    ]


def test_empty_page_with_cursor_continues() -> None:
    pages = [
        {"issues": [], "nextPageToken": "t1"},
        {"issues": [_issue("ABC-9")]},
    ]
    stub = _stub_search(pages)
    c = _connector()
    c._search = stub.__get__(c, type(c))  # type: ignore[method-assign]
    c._get_comments = MagicMock(return_value=[])  # type: ignore[method-assign]
    ids = [d.id for batch in c.load_from_state() for d in batch]
    assert ids == ["https://acme.atlassian.net/browse/ABC-9"]


def test_repeated_token_detects_cycle_and_raises() -> None:
    def repeater(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"issues": [_issue("ABC-1")], "nextPageToken": "loop"}

    c = _connector(batch_size=100)
    c._search = repeater.__get__(c, type(c))  # type: ignore[method-assign]
    c._get_comments = MagicMock(return_value=[])  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="Detected cycle in pagination cursor"):
        list(c.load_from_state())


def test_load_credentials_configures_session_auth() -> None:
    c = _connector()
    c.load_credentials({"email": "test@example.com", "api_token": "secret123"})
    assert c.email == "test@example.com"
    assert c.api_token == "secret123"
    assert c._session.auth == ("test@example.com", "secret123")


def test_poll_source_applies_time_range_filter() -> None:
    stub = _stub_search([{"issues": [_issue("ABC-1")]}])
    c = _connector()
    c._search = stub.__get__(c, type(c))  # type: ignore[method-assign]
    c._get_comments = MagicMock(return_value=[])  # type: ignore[method-assign]
    start_ts = 1704067200.0
    end_ts = 1704153600.0
    batches = list(c.poll_source(start=start_ts, end=end_ts))
    assert len(batches) == 1
    assert f"updated >= {int(start_ts * 1000)}" in stub.last_jql
    assert f"updated <= {int(end_ts * 1000)}" in stub.last_jql


def test_conversion_error_is_skipped_without_crashing_batch() -> None:
    pages = [{"issues": [{"key": 123}, _issue("ABC-GOOD")]}]
    stub = _stub_search(pages)
    c = _connector(batch_size=10)
    c._search = stub.__get__(c, type(c))  # type: ignore[method-assign]
    c._get_comments = MagicMock(return_value=[])  # type: ignore[method-assign]
    orig_conv = c._issue_to_document

    def fail_first(issue: dict[str, Any]) -> Any:
        if issue.get("key") == 123:
            raise ValueError("Malformed issue")
        return orig_conv(issue)

    c._issue_to_document = fail_first  # type: ignore[method-assign]
    batches = list(c.load_from_state())
    assert len(batches) == 1
    # 123 skipped due to ValueError, ABC-GOOD successfully returned
    assert [d.id for d in batches[0]] == ["https://acme.atlassian.net/browse/ABC-GOOD"]


def test_network_exception_propagates_from_yield_batches() -> None:
    def fail_search(*_args: Any, **_kwargs: Any) -> Any:
        raise requests.ConnectionError("Network connection reset")

    c = _connector()
    c._search = fail_search.__get__(c, type(c))  # type: ignore[method-assign]
    with pytest.raises(requests.ConnectionError, match="Network connection reset"):
        list(c.load_from_state())


def test_http_error_includes_response_body() -> None:
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.text = '{"errorMessages":["Field does not exist"]}'
    mock_resp.raise_for_status.side_effect = requests.HTTPError("400 Client Error")

    c = _connector()
    c._session.get = MagicMock(return_value=mock_resp)

    with pytest.raises(requests.HTTPError, match="Field does not exist"):
        c._get("/rest/api/3/search/jql")


# ------------------------------------------------------------- document & ADF
def test_issue_document_mapping_and_sections() -> None:
    c = _connector()
    c._get_comments = MagicMock(  # type: ignore[method-assign]
        return_value=[
            {
                "author": {"displayName": "Agent Alice"},
                "body": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Comment body"}],
                        }
                    ],
                },
            }
        ]
    )
    doc = c._issue_to_document(_issue("ABC-101"))
    assert doc.id == "https://acme.atlassian.net/browse/ABC-101"
    assert doc.semantic_identifier == "Summary ABC-101"
    assert doc.sections[0].link == "https://acme.atlassian.net/browse/ABC-101"
    assert "Desc" in doc.sections[0].text
    assert "Agent Alice: Comment body" in doc.sections[0].text
    assert doc.metadata["project"] == "ABC"
    assert doc.metadata["key"] == "ABC-101"
    assert doc.metadata["status"] == "Open"


# --------------------------------------------------------------------- slim
def test_slim_uses_interface_callback() -> None:
    pages = [
        {"issues": [_issue("ABC-1"), _issue("ABC-2")], "nextPageToken": "t1"},
        {"issues": [_issue("ABC-3")]},
    ]
    stub = _stub_search(pages)
    c = _connector()
    c._search = stub.__get__(c, type(c))  # type: ignore[method-assign]
    hb = HB()
    groups: list[list[SlimDocument]] = list(
        c.retrieve_all_slim_docs(start=None, end=None, callback=hb)
    )
    ids = [d.id for g in groups for d in g]
    assert ids == [
        "https://acme.atlassian.net/browse/ABC-1",
        "https://acme.atlassian.net/browse/ABC-2",
        "https://acme.atlassian.net/browse/ABC-3",
    ]
    assert hb.calls, "progress() should have been called"


def test_slim_stop_requested() -> None:
    pages = [{"issues": [_issue("ABC-1")], "nextPageToken": "t1"}]
    stub = _stub_search(pages + pages * 5)
    c = _connector()
    c._search = stub.__get__(c, type(c))  # type: ignore[method-assign]
    hb = HB(stop=True)
    with pytest.raises(RuntimeError, match="stop signal detected"):
        list(c.retrieve_all_slim_docs(callback=hb))


def test_yield_batches_reraises_json_decode_error() -> None:
    """Ensure requests.exceptions.JSONDecodeError is re-raised rather than swallowed."""
    c = _connector()
    c._search = MagicMock(return_value={"issues": [_issue("ABC-1")]})  # type: ignore[method-assign]
    c._issue_to_document = MagicMock(  # type: ignore[method-assign]
        side_effect=requests.exceptions.JSONDecodeError("Expecting value", "doc", 0)
    )
    with pytest.raises(requests.exceptions.JSONDecodeError):
        list(c._yield_batches("project = ABC"))
