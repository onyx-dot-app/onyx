"""Unit tests for Jira Service Management connector."""

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


def test_jsm_connector_initialization() -> None:
    """Test that JSM connector can be initialized with correct parameters."""
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        project_key="TEST",
    )

    assert connector.jira_base == "https://test.atlassian.net"
    assert connector.jira_project == "TEST"
    assert (
        connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    ), "JSM connector should have JIRA_SERVICE_MANAGEMENT as document source"


def test_jsm_connector_with_jql() -> None:
    """Test JSM connector initialization with JQL query."""
    jql_query = "project = 'SUPPORT' AND status = 'Open'"
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        jql_query=jql_query,
    )

    assert connector.jql_query == jql_query
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_connector_with_blacklist() -> None:
    """Test JSM connector with comment email blacklist."""
    blacklist = ["bot@example.com", "automation@example.com"]
    connector = JiraServiceManagementConnector(
        jira_base_url="https://test.atlassian.net",
        project_key="SUPPORT",
        comment_email_blacklist=blacklist,
    )

    assert connector.comment_email_blacklist == tuple(blacklist)
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT
