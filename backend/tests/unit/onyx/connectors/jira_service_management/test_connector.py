from unittest.mock import MagicMock

import pytest
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def issue_fixture() -> Issue:
    issue = MagicMock(spec=Issue)
    issue.key = "JSM-1"
    issue.id = "1"
    issue.raw = {"fields": {"description": "Test description"}}

    class Comment:
        comments: list = []

    class Fields:
        description = "Test description"
        summary = "Test summary"
        labels: list = []
        created = "2024-01-01T00:00:00.000+0000"
        updated = "2024-01-01T00:00:00.000+0000"
        comment = Comment()

    issue.fields = Fields()
    return issue


def test_jsm_connector_source() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
    )
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_process_issue_emits_jsm_source(issue_fixture: Issue) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
    )

    doc = process_jira_issue(
        jira_base_url=connector.jira_base,
        issue=issue_fixture,
        document_source=connector.document_source,
    )

    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
