from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira.connector import JiraConnectorCheckpoint, process_jira_issue
from onyx.connectors.jira_service_management.connector import (
    JSM_PROJECT_TYPE_JQL,
    JiraServiceManagementConnector,
)
from onyx.connectors.models import Document


@pytest.fixture
def mock_jira_client() -> MagicMock:
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock()
    return mock


@pytest.fixture
def create_mock_issue() -> Callable[..., MagicMock]:
    def _create_mock_issue(
        key: str = "IT-123",
        summary: str = "Broken laptop",
        project_key: str = "IT",
    ) -> MagicMock:
        mock_issue = MagicMock(spec=Issue)
        mock_issue.fields = MagicMock()
        mock_issue.key = key
        mock_issue.fields.summary = summary
        mock_issue.fields.updated = "2023-01-01T12:00:00.000+0000"
        mock_issue.fields.created = "2023-01-01T12:00:00.000+0000"
        mock_issue.fields.description = "Some description"
        mock_issue.fields.labels = []
        mock_issue.fields.reporter = None
        mock_issue.fields.assignee = None
        mock_issue.fields.priority = None
        mock_issue.fields.status = None
        mock_issue.fields.resolution = None
        mock_issue.fields.resolutiondate = None
        mock_issue.fields.duedate = None
        mock_issue.fields.issuetype = None
        mock_issue.fields.parent = None
        project = MagicMock()
        project.key = project_key
        project.name = "IT Support"
        mock_issue.fields.project = project
        return mock_issue

    return _create_mock_issue


def test_scope_defaults_to_service_desk_projects() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net"
    )
    assert connector.jql_query == JSM_PROJECT_TYPE_JQL

    jql = connector._get_jql_query(0, 1000)
    assert JSM_PROJECT_TYPE_JQL in jql
    assert "updated >= 0" in jql
    assert "updated <= 1000000" in jql


def test_explicit_project_key_preserved() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        project_key="IT",
    )
    assert connector.jql_query is None
    assert 'project = "IT"' in connector._get_jql_query(0, 1000)


def test_explicit_jql_preserved() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net",
        jql_query='project = "CUSTOM"',
    )
    assert connector.jql_query == 'project = "CUSTOM"'


def test_documents_stamped_as_jira_service_management(
    mock_jira_client: MagicMock, create_mock_issue: Callable[..., MagicMock]
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net"
    )
    connector._jira_client = mock_jira_client
    # force the v2 (server) path so we can avoid the v3 id-fetch flow
    mock_jira_client._options = {"rest_api_version": "2"}

    issue = create_mock_issue()
    with patch(
        "onyx.connectors.jira.connector._perform_jql_search",
        return_value=iter([issue]),
    ):
        checkpoint = connector.build_dummy_checkpoint()
        checkpoint.has_more = False
        output = list(connector.load_from_checkpoint(0, 1000, checkpoint))

    docs = [item for item in output if isinstance(item, Document)]
    assert len(docs) == 1
    assert docs[0].source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_process_jira_issue_default_source_unchanged(
    create_mock_issue: Callable[..., MagicMock],
) -> None:
    """The Jira connector still stamps plain JIRA on its documents."""
    issue = create_mock_issue()
    doc = process_jira_issue(jira_base_url="https://example.atlassian.net", issue=issue)
    assert doc is not None
    assert doc.source == DocumentSource.JIRA

    doc = process_jira_issue(
        jira_base_url="https://example.atlassian.net",
        issue=issue,
        source=DocumentSource.JIRA_SERVICE_MANAGEMENT,
    )
    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_checkpoint_type_is_jira_checkpoint() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net"
    )
    checkpoint = connector.build_dummy_checkpoint()
    assert isinstance(checkpoint, JiraConnectorCheckpoint)
    assert checkpoint.has_more is True
