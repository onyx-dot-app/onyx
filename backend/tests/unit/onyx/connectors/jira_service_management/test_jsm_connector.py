from unittest.mock import MagicMock

import pytest
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


@pytest.fixture
def mock_jsm_issue() -> MagicMock:
    issue = MagicMock(spec=Issue)
    fields = MagicMock()
    fields.description = "Customer cannot access the portal"
    fields.comment = MagicMock()
    fields.comment.comments = [MagicMock(body="Please share screenshots")]
    fields.reporter = MagicMock()
    fields.reporter.displayName = "Jane Customer"
    fields.reporter.emailAddress = "jane@example.com"
    fields.assignee = MagicMock()
    fields.assignee.displayName = "Sam Agent"
    fields.assignee.emailAddress = "sam@example.com"
    fields.summary = "Cannot log in"
    fields.updated = "2023-01-01T00:00:00+0000"
    fields.labels = []
    issue.fields = fields
    issue.key = "JSM-1"
    return issue


def test_jsm_connector_subclasses_jira_connector() -> None:
    """JSM reuses the Jira connector wholesale; the only difference is source."""
    assert issubclass(JiraServiceManagementConnector, JiraConnector)


def test_jsm_connector_class_source_is_jsm() -> None:
    assert (
        JiraServiceManagementConnector.source
        == DocumentSource.JIRA_SERVICE_MANAGEMENT
    )
    # Verify the base Jira connector still emits regular JIRA documents
    assert JiraConnector.source == DocumentSource.JIRA


def test_jsm_connector_instance_carries_jsm_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jsm.example.com",
        project_key="HELP",
    )
    assert connector.source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_process_jira_issue_defaults_to_jira_source(
    mock_jsm_issue: MagicMock,
) -> None:
    doc = process_jira_issue("https://jira.example.com", mock_jsm_issue)
    assert doc is not None
    assert doc.source == DocumentSource.JIRA


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
