"""Unit tests for the Jira Service Management connector (no network)."""
from datetime import datetime, timezone

from onyx.connectors.jira_service_management.jira_service_management_connector import (
    JiraServiceManagementConnector,
)


def _connector(request_jql: str | None = None):
    return JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="SUP",
        request_jql=request_jql,
    )


def test_adf_to_text_flattens_paragraphs_and_text():
    adf = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "hello "},
                                               {"type": "text", "text": "world"}]},
        ],
    }
    out = JiraServiceManagementConnector._adf_to_text(adf)
    assert "hello" in out and "world" in out


def test_adf_to_text_handles_none_and_string():
    assert JiraServiceManagementConnector._adf_to_text(None) == ""
    assert JiraServiceManagementConnector._adf_to_text("plain") == "plain"


def test_request_jql_enforces_project_scope():
    # No custom JQL -> plain project constraint.
    assert _connector().request_jql == 'project = "SUP"'
    # Custom JQL is wrapped in parentheses and AND-ed after project scope, so an
    # `OR` inside the custom clause cannot escape the project.
    c = _connector(request_jql='status = "Open" OR status = "Done"')
    assert c.request_jql.startswith('project = "SUP" AND (')
    assert c.request_jql.endswith(")")
    assert 'OR status = "Done"' in c.request_jql


def test_issue_to_document_builds_sections_and_metadata(monkeypatch):
    c = _connector()
    # Comments are fetched from the dedicated (paginated) comments endpoint.
    monkeypatch.setattr(
        c,
        "_get_comments",
        lambda key: [
            {"author": {"displayName": "Agent"},
             "body": {"type": "doc", "content": [
                 {"type": "paragraph", "content": [{"type": "text", "text": "Investigating."}]}]}}
        ],
    )
    issue = {
        "key": "SUP-42",
        "fields": {
            "summary": "Login broken",
            "description": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Users cannot log in."}]}]},
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "created": "2024-01-01T00:00:00.000+0000",
            "updated": "2024-01-02T00:00:00.000+0000",
        },
    }
    doc = c._issue_to_document(issue)
    assert doc.id == "SUP-42"
    assert "Login broken" in doc.semantic_identifier
    # Section text is a model attribute, not a dict index.
    assert "Users cannot log in." in doc.sections[0].text
    assert "Investigating." in doc.sections[0].text
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["project"] == "SUP"
    assert doc.sections[0].link.endswith("/browse/SUP-42")


def test_get_comments_follows_pagination(monkeypatch):
    c = _connector()
    pages = [
        {"comments": [{"body": "c1"}, {"body": "c2"}], "total": 3, "startAt": 0},
        {"comments": [{"body": "c3"}], "total": 3, "startAt": 2},
    ]
    calls = {"n": 0}

    def fake_get(path, params=None):
        page = pages[calls["n"]]
        calls["n"] += 1
        return page

    monkeypatch.setattr(c, "_get", fake_get)
    comments = c._get_comments("SUP-1")
    assert [cm["body"] for cm in comments] == ["c1", "c2", "c3"]


def test_yield_batches_paginates_by_next_page_token(monkeypatch):
    c = _connector(batch_size=1)
    pages = {
        None: {"issues": [{"key": "A", "fields": {"summary": "a"}}], "nextPageToken": "t2"},
        "t2": {"issues": [{"key": "B", "fields": {"summary": "b"}}]},
    }
    monkeypatch.setattr(c, "_search", lambda jql, tok: pages[tok])
    monkeypatch.setattr(c, "_get_comments", lambda key: [])
    yielded_ids = []
    for docs, _failures in c._yield_batches('project = "SUP"'):
        yielded_ids.extend(d.id for d in docs)
    assert yielded_ids == ["A", "B"]
