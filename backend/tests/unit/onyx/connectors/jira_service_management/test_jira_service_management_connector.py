"""Unit tests for the Jira Service Management connector (offline, no network)."""

from __future__ import annotations

from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from onyx.connectors.interfaces import GenerateDocumentsOutput, SlimDocument
from onyx.connectors.jira_service_management.jira_service_management_connector import (
    JiraServiceManagementConnector,
    _validate_base_url,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface


class HB(IndexingHeartbeatInterface):
    """Minimal heartbeat implementing the real interface contract."""

    def __init__(self, stop: bool = False) -> None:
        super().__init__()
        self._stop = stop
        self.calls: list[tuple[str, int]] = []

    def should_stop(self) -> bool:
        return self._stop

    def progress(self, tag: str, amount: int) -> None:
        self.calls.append((tag, amount))


def _connector(
    request_jql: str | None = None,
    batch_size: int = 10,
    base_url: str = "https://acme.atlassian.net",
) -> JiraServiceManagementConnector:
    return JiraServiceManagementConnector(
        base_url=base_url,
        project_key="ABC",
        batch_size=batch_size,
        request_jql=request_jql,
    )


def _issue(key: str) -> dict[str, Any]:
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

    def _search(self: Any, jql: str, token: str | None) -> dict[str, Any]:
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


def test_http_loopback_allowed() -> None:
    assert _validate_base_url("http://localhost:2990") == "http://localhost:2990"
    assert _validate_base_url("http://127.0.0.1") == "http://127.0.0.1"


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
    assert c.request_jql == (
        'project = "ABC" AND (status = Open OR status = Closed)'
    )


def test_no_request_jql_shows_project_only() -> None:
    c = _connector()
    assert c.request_jql == 'project = "ABC"'


def test_project_key_validated() -> None:
    with pytest.raises(ValueError):
        JiraServiceManagementConnector(
            base_url="https://x.atlassian.net", project_key='ABC" OR 1=1'
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
    assert ids == ["ABC-1", "ABC-2", "ABC-3"]


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
    assert ids == ["ABC-9"]


def test_repeated_token_does_not_hang() -> None:
    # Every page returns the same nextPageToken -> must terminate.
    class Repeater:
        def __call__(self, self_c: Any, jql: str, token: str | None) -> dict[str, Any]:
            return {"issues": [_issue("ABC-1")], "nextPageToken": "loop"}

    c = _connector(batch_size=100)
    c._search = Repeater().__get__(c, type(c))  # type: ignore[method-assign]
    c._get_comments = MagicMock(return_value=[])  # type: ignore[method-assign]
    docs = [d.id for batch in c.load_from_state() for d in batch]
    # Terminates after the cursor repeats; exactly two pages are read.
    assert docs == ["ABC-1", "ABC-1"]


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
    assert ids == ["ABC-1", "ABC-2", "ABC-3"]
    assert hb.calls, "progress() should have been called"


def test_slim_stop_requested() -> None:
    pages = [{"issues": [_issue("ABC-1")], "nextPageToken": "t1"}]
    stub = _stub_search(pages + pages * 5)
    c = _connector()
    c._search = stub.__get__(c, type(c))  # type: ignore[method-assign]
    hb = HB(stop=True)
    out = [d.id for g in c.retrieve_all_slim_docs(callback=hb) for d in g]
    assert out == ["ABC-1"]
