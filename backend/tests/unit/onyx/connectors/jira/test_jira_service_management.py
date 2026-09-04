from unittest.mock import MagicMock

import pytest
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import JiraServiceManagementConnector
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


@pytest.fixture
def mock_issue() -> MagicMock:
    issue = MagicMock(spec=Issue)
    fields = MagicMock()
    fields.description = "A customer cannot log in"
    fields.comment = MagicMock()
    fields.comment.comments = [MagicMock(body="We are looking into it")]
    fields.reporter = MagicMock()
    fields.reporter.displayName = "John Doe"
    fields.reporter.emailAddress = "john@example.com"
    fields.assignee = MagicMock()
    fields.assignee.displayName = "Jane Doe"
    fields.assignee.emailAddress = "jane@example.com"
    fields.summary = "Login broken"
    fields.updated = "2023-01-01T00:00:00+0000"
    fields.labels = []

    issue.fields = fields
    issue.key = "SUP-1"
    return issue


def test_process_jira_issue_defaults_to_jira_source(mock_issue: MagicMock) -> None:
    """By default the shared processing helper tags documents as plain Jira."""
    doc = process_jira_issue("https://example.atlassian.net", mock_issue)

    assert doc is not None
    assert doc.source == DocumentSource.JIRA


def test_process_jira_issue_honors_explicit_source(mock_issue: MagicMock) -> None:
    """When a source is provided, the emitted document is tagged with it.

    This is what lets Jira Service Management tickets be indexed as a distinct
    source while reusing all of the Jira processing logic.
    """
    doc = process_jira_issue(
        "https://example.atlassian.net",
        mock_issue,
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
    )

    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_connector_reuses_jira_logic_with_jsm_source() -> None:
    """The JSM connector is a thin JiraConnector subclass pinned to the JSM source."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="SUP",
    )

    assert isinstance(connector, JiraConnector)
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    # The base Jira connector still defaults to the plain Jira source.
    assert (
        JiraConnector(jira_base_url="https://example.atlassian.net").document_source
        == DocumentSource.JIRA
    )


def test_jsm_connector_source_cannot_be_overridden() -> None:
    """A caller cannot accidentally make the JSM connector emit plain Jira docs."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        document_source=DocumentSource.JIRA,
    )

    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_registry_maps_jsm_to_jsm_connector() -> None:
    """The factory must be able to lazily load the JSM connector class."""
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]

    assert mapping.module_path == "onyx.connectors.jira.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"
