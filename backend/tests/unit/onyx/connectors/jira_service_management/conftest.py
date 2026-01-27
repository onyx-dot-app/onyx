"""Pytest fixtures for Jira Service Management connector tests."""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira import JIRA
from jira.resources import Issue

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.jira.utils import JIRA_SERVER_API_VERSION


@pytest.fixture
def jira_base_url() -> str:
    """Fixture providing a test Jira base URL."""
    return "https://jira.example.com"


@pytest.fixture
def jsm_project_key() -> str:
    """Fixture providing a test JSM project key."""
    return "ITSM"


@pytest.fixture
def user_email() -> str:
    """Fixture providing a test user email."""
    return "test@example.com"


@pytest.fixture
def mock_jira_api_token() -> str:
    """Fixture providing a mock API token."""
    return "token123"


@pytest.fixture
def mock_jira_client() -> MagicMock:
    """Create a mock JIRA client with proper typing."""
    mock = MagicMock(spec=JIRA)
    mock.search_issues = MagicMock()
    mock.project = MagicMock()
    mock.projects = MagicMock()
    mock._session = MagicMock()
    mock._get_url = MagicMock(return_value="https://jira.example.com/rest/api/3/")
    mock._options = MagicMock(return_value={"rest_api_version": JIRA_SERVER_API_VERSION})
    mock.client_info = MagicMock(return_value="https://jira.example.com")
    return mock


@pytest.fixture
def jsm_connector(
    jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
) -> Generator[JiraServiceManagementConnector, None, None]:
    """Fixture providing a configured JSM connector with mocked client."""
    connector = JiraServiceManagementConnector(
        jira_base_url=jira_base_url,
        jsm_project_key=jsm_project_key,
        comment_email_blacklist=["blacklist@example.com"],
        labels_to_skip=["secret", "sensitive"],
    )
    connector._jira_client = mock_jira_client
    connector._jira_client.client_info.return_value = jira_base_url
    with patch("onyx.connectors.jira_service_management.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector


@pytest.fixture
def create_mock_issue() -> callable:
    """Helper fixture to create mock Issue objects."""
    def _create_mock_issue(
        key: str = "ITSM-123",
        summary: str = "Test JSM Issue",
        updated: str = "2023-01-01T12:00:00.000+0000",
        description: str = "Test Description",
        labels: list[str] | None = None,
    ) -> MagicMock:
        """Create a mock Issue object."""
        mock_issue = MagicMock(spec=Issue)
        mock_issue.fields = MagicMock()
        mock_issue.key = key
        mock_issue.fields.summary = summary
        mock_issue.fields.updated = updated
        mock_issue.fields.description = description
        mock_issue.fields.labels = labels or []

        # Set up reporter and assignee
        mock_issue.fields.reporter = MagicMock()
        mock_issue.fields.reporter.displayName = "Test Reporter"
        mock_issue.fields.reporter.emailAddress = "reporter@example.com"

        mock_issue.fields.assignee = MagicMock()
        mock_issue.fields.assignee.displayName = "Test Assignee"
        mock_issue.fields.assignee.emailAddress = "assignee@example.com"

        # Set up priority, status
        mock_issue.fields.priority = MagicMock()
        mock_issue.fields.priority.name = "High"

        mock_issue.fields.status = MagicMock()
        mock_issue.fields.status.name = "Open"

        # Add raw field
        mock_issue.raw = {"fields": {"description": description}}

        return mock_issue

    return _create_mock_issue
