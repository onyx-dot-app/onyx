"""Unit tests for the Jira Service Management connector.

The connector is a thin subclass of JiraConnector — these tests mostly verify
the wiring (subclass identity, source tagging, registry mapping) since all
ingestion behaviour is covered by the parent connector's existing test suite.
"""

from unittest.mock import MagicMock

from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


def _make_mock_issue(key: str = "SUP-1", summary: str = "Login broken") -> MagicMock:
    issue = MagicMock(spec=Issue)
    fields = MagicMock()
    fields.description = "Customer cannot log in"
    fields.comment = MagicMock()
    fields.comment.comments = [
        MagicMock(body="Have you tried clearing cookies?"),
    ]
    fields.reporter = MagicMock()
    fields.reporter.displayName = "Customer A"
    fields.reporter.emailAddress = "customer@example.com"
    fields.assignee = MagicMock()
    fields.assignee.displayName = "Agent B"
    fields.assignee.emailAddress = "agent@example.com"
    fields.summary = summary
    fields.updated = "2024-01-01T00:00:00+0000"
    fields.labels = []
    issue.fields = fields
    issue.key = key
    return issue


def test_jsm_connector_is_jira_subclass() -> None:
    """JSM connector inherits from JiraConnector to share ingestion logic."""
    assert issubclass(JiraServiceManagementConnector, JiraConnector)


def test_jsm_connector_source_is_jira_service_management() -> None:
    """The class-level _source attribute drives DocumentSource tagging."""
    assert (
        JiraServiceManagementConnector._source
        == DocumentSource.JIRA_SERVICE_MANAGEMENT
    )
    # Sanity check: parent connector still tags as plain Jira.
    assert JiraConnector._source == DocumentSource.JIRA


def test_jsm_connector_constructs_with_jira_args() -> None:
    """JSM accepts the same constructor args as JiraConnector."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="SUP",
        comment_email_blacklist=["bot@example.com"],
        labels_to_skip=["internal"],
    )
    assert connector.jira_base == "https://example.atlassian.net"
    assert connector.jira_project == "SUP"
    assert connector._source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_process_jira_issue_respects_source_override() -> None:
    """process_jira_issue tags the produced Document with the supplied source."""
    issue = _make_mock_issue()

    default_doc = process_jira_issue("https://example.atlassian.net", issue)
    assert default_doc is not None
    assert default_doc.source == DocumentSource.JIRA

    jsm_doc = process_jira_issue(
        "https://example.atlassian.net",
        issue,
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
    )
    assert jsm_doc is not None
    assert jsm_doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    # Same content, different source tag.
    assert jsm_doc.id == default_doc.id
    assert jsm_doc.semantic_identifier == default_doc.semantic_identifier


def test_jsm_connector_registered_in_registry() -> None:
    """Registry maps DocumentSource.JIRA_SERVICE_MANAGEMENT to the JSM connector."""
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert mapping.module_path == "onyx.connectors.jira_service_management.connector"
    assert mapping.class_name == "JiraServiceManagementConnector"
