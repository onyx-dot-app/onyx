from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


@pytest.fixture
def mock_jsm_issue() -> MagicMock:
    issue = MagicMock()
    issue.key = "JSM-1"
    issue.fields.summary = "Cannot log in"
    issue.fields.description = "User reports they cannot log in to the portal."
    issue.fields.updated = "2026-05-19T17:00:00.000+0000"
    issue.fields.created = "2026-05-19T16:00:00.000+0000"
    issue.fields.creator.emailAddress = "creator@example.com"
    issue.fields.reporter.emailAddress = "reporter@example.com"
    issue.fields.assignee = None
    issue.fields.priority.name = "High"
    issue.fields.status.name = "Open"
    issue.fields.resolution = None
    issue.fields.issuetype.name = "Incident"
    issue.fields.labels = []
    issue.fields.comment.comments = []
    return issue


def test_process_jira_issue_honors_source_override(
    mock_jsm_issue: MagicMock,
) -> None:
    doc = process_jira_issue(
        "https://jsm.example.com",
        mock_jsm_issue,
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
    )
    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.id == "https://jsm.example.com/browse/JSM-1"
    assert doc.semantic_identifier == "JSM-1: Cannot log in"


def test_jsm_registered_in_connector_map() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"
