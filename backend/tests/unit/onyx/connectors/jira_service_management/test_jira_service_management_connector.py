from collections.abc import Generator
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def jsm_project_key() -> str:
    return "HELPDESK"


@pytest.fixture
def mock_source_operations() -> MagicMock:
    return create_autospec(JiraSourceOperations, instance=True)


@pytest.fixture
def jsm_connector(
    jsm_project_key: str, mock_source_operations: MagicMock
) -> Generator[JiraServiceManagementConnector, None, None]:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key=jsm_project_key,
        labels_to_skip=["secret"],
    )
    connector._source_operations = mock_source_operations
    yield connector


def test_validate_connector_settings_accepts_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
    jsm_project_key: str,
) -> None:
    mock_source_operations.get_project.return_value = {
        "key": jsm_project_key,
        "projectTypeKey": "service_desk",
        "name": "Help Desk",
    }

    jsm_connector.validate_connector_settings()

    mock_source_operations.get_project.assert_called_once_with(
        project_key=jsm_project_key
    )


def test_validate_connector_settings_rejects_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
    jsm_project_key: str,
) -> None:
    mock_source_operations.get_project.return_value = {
        "key": jsm_project_key,
        "projectTypeKey": "software",
        "name": "Engineering",
    }

    with pytest.raises(
        ConnectorValidationError,
        match=f"Project {jsm_project_key!r} is a Jira software project",
    ):
        jsm_connector.validate_connector_settings()


def test_validate_connector_settings_rejects_unknown_project_type(
    jsm_connector: JiraServiceManagementConnector,
    mock_source_operations: MagicMock,
) -> None:
    mock_source_operations.get_project.return_value = {
        "key": "HELPDESK",
        "name": "Help Desk",
    }

    with pytest.raises(ConnectorValidationError):
        jsm_connector.validate_connector_settings()


def test_validate_connector_settings_skips_project_type_check_for_jql(
    mock_source_operations: MagicMock,
) -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        jql_query="project = HELPDESK",
    )
    connector._source_operations = mock_source_operations

    with patch("onyx.connectors.jira.connector._perform_jql_search", return_value=[]):
        connector.validate_connector_settings()

    # A custom JQL can span projects, so the service-desk gate stays off.
    mock_source_operations.get_project.assert_not_called()


def test_load_credentials_uses_jsm_source(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    jsm_connector.load_credentials(
        {
            "jira_base_url": "https://jira.example.com",
            "jira_user_email": "agent@example.com",
            "jira_api_token": "token",
        }
    )

    assert isinstance(jsm_connector._source_operations, JiraSourceOperations)
    provider = jsm_connector._source_operations.credentials_provider
    assert provider._connector_name == DocumentSource.JIRA_SERVICE_MANAGEMENT.value  # ty: ignore[unresolved-attribute]


def test_project_scoped_jql_defaults_to_jsm_project(
    jsm_connector: JiraServiceManagementConnector, jsm_project_key: str
) -> None:
    jql = jsm_connector._get_jql_query(start=0, end=1)

    assert f'project = "{jsm_project_key}"' in jql
