from types import SimpleNamespace
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
    issue.key = "HELP-1"
    issue.raw = {"fields": {"description": "Customer cannot log in"}}
    issue.fields = SimpleNamespace(
        summary="Cannot log in",
        description="Customer cannot log in",
        comment=SimpleNamespace(comments=[]),
        labels=[],
        updated="2023-01-01T00:00:00.000+0000",
        created="2023-01-01T00:00:00.000+0000",
        issuetype=SimpleNamespace(name="Service Request"),
        priority=SimpleNamespace(name="Medium"),
        status=SimpleNamespace(name="Open"),
        resolution=None,
        resolutiondate=None,
        duedate=None,
        reporter=None,
        assignee=None,
        parent=None,
        project=SimpleNamespace(key="HELP", name="Help Desk"),
    )
    return issue


def test_jsm_connector_subclasses_jira_connector() -> None:
    assert issubclass(JiraServiceManagementConnector, JiraConnector)


def test_jsm_connector_source() -> None:
    assert JiraServiceManagementConnector.source == DocumentSource.JIRA_SERVICE_MANAGEMENT

    assert JiraConnector.source == DocumentSource.JIRA


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
    assert doc.id == "https://jsm.example.com/browse/HELP-1"
    assert doc.semantic_identifier == "HELP-1: Cannot log in"


def test_jsm_registered_in_connector_map() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"

