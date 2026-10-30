"""Unit tests for the Jira Service Management connector (no network)."""
from datetime import datetime, timezone
from typing import Any

import pytest

from onyx.connectors.jira_service_management.jira_service_management_connector import (
    JiraServiceManagementConnector,
)


def _connector(
    request_jql: str | None = None,
    batch_size: int = 10,
) -> JiraServiceManagementConnector:
    return JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="SUP",
        batch_size=batch_size,
        request_jql=request_jql,
    )


def test_adf_to_text_flattens_paragraphs_and_text() -> None:
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "hello "},
                    {"type": "text", "text": "world"},
                ],
            },
        ],
    }
    out = JiraServiceManagementConnector._adf_to_text(adf)
    assert "hello" in out and "world" in out


def test_adf_to_text_handles_none_and_string() -> None:
    assert JiraServiceManagementConnector._adf_to_text(None) == ""
    assert JiraServiceManagementConnector._adf_to_text("plain") == "plain"


def test_request_jql_enforces_project_scope() -> None:
    assert _connector().request_jql == 'project = "SUP"'
    c = _connector(request_jql='status = "Open" OR status = "Done"')
    assert c.request_jql.startswith('project = "SUP" AND (')
    assert c.request_jql.endswith(")")
    assert 'OR status = "Done"' in c.request_jql


def test_invalid_project_key_rejected() -> None:
    with pytest.raises(ValueError):
        JiraServiceManagementConnector(
            base_url="https://example.atlassian.net",
            project_key='SUP" OR project = "OTHER',
        )


def test_issue_to_document_builds_sections_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = _connector()
    monkeypatch.setattr(
        c,
        "_get_comments",
        lambda key: [
            {
                "author": {"displayName": "Agent"},
                "body": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Investigating."}],
                        }
                    ],
                },
            }
        ],
    )
    issue = {
        "key": "SUP-42",
        "fields": {
            "summary": "Login broken",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Users cannot log in."}],
                    }
                ],
            },
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "created": "2024-01-01T00:00:00.000+0000",
            "updated": "2024-01-02T00:00:00.000+0000",
        },
    }
    doc = c._issue_to_document(issue)
    assert doc.id == "SUP-42"
    assert "Login broken" in doc.semantic_identifier
    assert "Users cannot log in." in doc.sections[0].text
    assert "Investigating." in doc.sections[0].text
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["project"] == "SUP"
    assert doc.sections[0].link.endswith("/browse/SUP-42")


def test_get_comments_follows_pagination(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    pages = [
        {"comments": [{"body": "c1"}, {"body": "c2"}], "total": 3, "startAt": 0},
        {"comments": [{"body": "c3"}], "total": 3, "startAt": 2},
    ]
    calls = {"n": 0}

    def fake_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        page = pages[calls["n"]]
        calls["n"] += 1
        return page

    monkeypatch.setattr(c, "_get", fake_get)
    comments = c._get_comments("SUP-1")
    assert [cm["body"] for cm in comments] == ["c1", "c2", "c3"]


def test_yield_batches_paginates_by_next_page_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = _connector(batch_size=1)
    pages: dict[str | None, dict[str, Any]] = {
        None: {"issues": [{"key": "A", "fields": {"summary": "a"}}], "nextPageToken": "t2"},
        "t2": {"issues": [{"key": "B", "fields": {"summary": "b"}}]},
    }
    monkeypatch.setattr(c, "_search", lambda jql, tok: pages[tok])
    monkeypatch.setattr(c, "_get_comments", lambda key: [])
    yielded_ids: list[str] = []
    for docs in c._yield_batches('project = "SUP"'):
        yielded_ids.extend(d.id for d in docs)
    assert yielded_ids == ["A", "B"]


def test_yield_batches_continues_on_empty_page_with_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An empty page that still carries a nextPageToken must not stop iteration.
    c = _connector(batch_size=1)
    pages: dict[str | None, dict[str, Any]] = {
        None: {"issues": [], "nextPageToken": "t2"},
        "t2": {"issues": [{"key": "B", "fields": {"summary": "b"}}]},
    }
    monkeypatch.setattr(c, "_search", lambda jql, tok: pages[tok])
    monkeypatch.setattr(c, "_get_comments", lambda key: [])
    ids = [d.id for docs in c._yield_batches('project = "SUP"') for d in docs]
    assert ids == ["B"]


def test_slim_docs_uses_callback_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    c = _connector()
    monkeypatch.setattr(
        c, "_search", lambda jql, tok: {"issues": [{"key": "A"}, {"key": "B"}]}
    )

    class HB:
        def __init__(self) -> None:
            self.progress_calls: list[tuple[str, int]] = []

        def should_stop(self) -> bool:
            return False

        def progress(self, tag: str, amount: int) -> None:
            self.progress_calls.append((tag, amount))

    hb = HB()
    ids = [d.id for batch in c.retrieve_all_slim_docs(callback=hb) for d in batch]
    assert ids == ["A", "B"]
    assert hb.progress_calls == [("jira_service_management", 2)]
