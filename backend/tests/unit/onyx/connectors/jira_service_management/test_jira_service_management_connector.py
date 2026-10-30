"""Unit tests for the Jira Service Management connector (no network)."""
from datetime import datetime, timezone

from onyx.connectors.jira_service_management.jira_service_management_connector import (
    JiraServiceManagementConnector,
)


def _connector():
    c = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net", project_key="SUP"
    )
    return c


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


def test_issue_to_document_builds_sections_and_metadata():
    c = _connector()
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
            "comment": {"comments": [
                {"author": {"displayName": "Agent"},
                 "body": {"type": "doc", "content": [
                     {"type": "paragraph", "content": [{"type": "text", "text": "Investigating."}]}]}}]},
        },
    }
    doc = c._issue_to_document(issue)
    assert doc.id == "SUP-42"
    assert "Login broken" in doc.semantic_identifier
    assert "Users cannot log in." in doc.sections[0]["text"]
    assert "Investigating." in doc.sections[0]["text"]
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["project"] == "SUP"
    assert doc.sections[0]["link"].endswith("/browse/SUP-42")
