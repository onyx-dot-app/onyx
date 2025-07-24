from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from jira import JIRA

from onyx.connectors.jira.connector import JiraConnector


@pytest.fixture
def jira_base_url() -> str:
    return "https://jira.example.com"


@pytest.fixture
def project_key() -> str:
    return "TEST"


@pytest.fixture
def user_email() -> str:
    return "test@test.com"


@pytest.fixture
def mock_jira_api_token() -> str:
    return "token123"


@pytest.fixture
def mock_jira_client() -> MagicMock:
    """Create a mock JIRA client with proper typing"""
    mock = MagicMock(spec=JIRA)
    # Add proper return typing for search_issues method
    mock.search_issues = MagicMock()
    # Add proper return typing for project method
    mock.project = MagicMock()
    # Add proper return typing for projects method
    mock.projects = MagicMock()
    return mock


@pytest.fixture
def jira_connector(
    jira_base_url: str, project_key: str, mock_jira_client: MagicMock
) -> Generator[JiraConnector, None, None]:
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key=project_key,
        comment_email_blacklist=["blacklist@example.com"],
        labels_to_skip=["secret", "sensitive"],
    )
    connector._jira_client = mock_jira_client
    connector._jira_client.client_info.return_value = jira_base_url
    with patch("onyx.connectors.jira.connector._JIRA_FULL_PAGE_SIZE", 2):
        yield connector
