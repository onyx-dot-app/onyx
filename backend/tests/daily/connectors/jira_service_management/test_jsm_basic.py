"""Tests for the Jira Service Management connector.

Verifies JSM-specific behavior: request_type extraction, JSM document source,
and JQL query construction with issuetype filters.
"""

from unittest.mock import MagicMock

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    _extract_request_type,
)
from onyx.connectors.models import Document


class MockJiraIssue:
    """Minimal mock of a jira.resources.Issue for unit testing."""

    def __init__(
        self,
        key: str = "SUPPORT-1",
        summary: str = "Test ticket",
        description: str = "Test description",
        status_name: str = "Open",
        priority_name: str = "Medium",
        issuetype_name: str = "Service Request",
        labels: list[str] | None = None,
        created: str = "2025-01-01T00:00:00.000+0000",
        updated: str = "2025-06-01T00:00:00.000+0000",
        reporter_name: str = "Test User",
        reporter_email: str = "test@example.com",
        assignee_name: str | None = "Agent",
        assignee_email: str | None = "agent@example.com",
        project_key: str = "SUPPORT",
        project_name: str = "Support Desk",
    ):
        self.key = key
        self.fields = MagicMock()
        self.fields.summary = summary
        self.fields.description = description
        self.fields.labels = labels or []
        self.fields.created = created
        self.fields.updated = updated
        self.fields.duedate = None
        self.fields.status = MagicMock()
        self.fields.status.name = status_name
        self.fields.priority = MagicMock()
        self.fields.priority.name = priority_name
        self.fields.issuetype = MagicMock()
        self.fields.issuetype.name = issuetype_name
        self.fields.resolution = None
        self.fields.reporter = MagicMock()
        self.fields.reporter.displayName = reporter_name
        self.fields.reporter.emailAddress = reporter_email
        self.fields.assignee = MagicMock()
        self.fields.assignee.displayName = assignee_name
        self.fields.assignee.emailAddress = assignee_email
        self.fields.project = MagicMock()
        self.fields.project.key = project_key
        self.fields.project.name = project_name
        self.fields.comment = MagicMock()
        self.fields.comment.comments = []
        self.raw = {"fields": {"description": None}}


# --- _extract_request_type tests ---


def test_extract_request_type_from_custom_field() -> None:
    issue = MockJiraIssue()
    issue.raw["fields"]["customfield_10010"] = {"name": "Password Reset"}
    assert _extract_request_type(issue) == "Password Reset"


def test_extract_request_type_from_string_field() -> None:
    issue = MockJiraIssue()
    issue.raw["fields"]["customfield_10001"] = "Hardware Issue"
    assert _extract_request_type(issue) == "Hardware Issue"


def test_extract_request_type_from_issuetype() -> None:
    issue = MockJiraIssue(issuetype_name="Incident")
    assert _extract_request_type(issue) == "Incident"


def test_extract_request_type_none() -> None:
    issue = MockJiraIssue()
    issue.fields.issuetype = MagicMock(spec=[])
    assert _extract_request_type(issue) is None


# --- Connector class tests ---


def test_connector_inherits_from_jira() -> None:
    assert issubclass(JiraServiceManagementConnector, JiraConnector)


def test_connector_default_init() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        project_key="SUP",
    )
    assert c.jira_base == "https://ex.atlassian.net"
    assert c.jira_project == "SUP"
    assert c.include_request_types is None


def test_connector_with_request_types() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        project_key="SUP",
        include_request_types=["Service Request", "Incident"],
    )
    assert c.include_request_types == ["Service Request", "Incident"]


# --- JQL query tests ---


def test_jql_with_request_types_filter() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        project_key="SUP",
        include_request_types=["Service Request", "Incident"],
    )
    jql = c._get_jql_query(0, 9999999999)
    assert 'issuetype in ("Service Request", "Incident")' in jql
    assert "project = " in jql
    assert "updated >=" in jql


def test_jql_without_request_types_filter() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        project_key="SUP",
    )
    jql = c._get_jql_query(0, 9999999999)
    assert "issuetype" not in jql


def test_jql_custom_jql_combined() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        jql_query='issuetype = "Bug"',
        include_request_types=["Bug"],
    )
    jql = c._get_jql_query(0, 9999999999)
    assert "issuetype =" in jql
    assert "issuetype in" in jql


# --- Document processing tests ---


def test_process_ticket_returns_document() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        project_key="SUP",
    )
    c.labels_to_skip = set()
    c._comment_email_blacklist = []

    issue = MockJiraIssue()
    issue.raw["fields"]["customfield_10010"] = {"name": "Password Reset"}

    doc = c._process_issue_as_jsm_ticket(issue)
    assert doc is not None
    assert isinstance(doc, Document)
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.metadata["request_type"] == "Password Reset"
    assert doc.metadata["key"] == "SUPPORT-1"
    assert doc.metadata["status"] == "Open"
    assert doc.metadata["priority"] == "Medium"
    assert doc.metadata["project"] == "SUPPORT"


def test_process_ticket_skips_labeled() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        project_key="SUP",
        labels_to_skip=["sensitive"],
    )
    c._comment_email_blacklist = []
    issue = MockJiraIssue(labels=["sensitive"])
    assert c._process_issue_as_jsm_ticket(issue) is None


def test_process_ticket_includes_people() -> None:
    c = JiraServiceManagementConnector(
        jira_base_url="https://ex.atlassian.net",
        project_key="SUP",
    )
    c.labels_to_skip = set()
    c._comment_email_blacklist = []
    issue = MockJiraIssue()
    doc = c._process_issue_as_jsm_ticket(issue)
    assert doc is not None
    assert doc.primary_owners is not None
    assert len(doc.primary_owners) == 2
