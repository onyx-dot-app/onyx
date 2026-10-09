"""Tests for Jira connector error handling during indexing."""

import time
from unittest.mock import MagicMock

import pytest

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.source_operations import JiraApiError
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector

_MISSING_PROJECT_TEXT = (
    '{"errorMessages":["The value \'INVALID_PROJECT\' does not exist for the '
    'field \'project\'."],"errors":{}}'
)


@pytest.fixture
def jira_connector_with_invalid_project(
    jira_base_url: str, mock_source_operations: MagicMock
) -> JiraConnector:
    """Create a Jira connector with an invalid project key."""
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key="INVALID_PROJECT",
    )
    connector._source_operations = mock_source_operations
    return connector


def _load(connector: JiraConnector) -> None:
    list(load_everything_from_checkpoint_connector(connector, 0, time.time()))


def test_nonexistent_project_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Test that a non-existent project error during indexing is properly handled."""
    mock_source_operations.search_issues.side_effect = JiraApiError(
        "error", status_code=400, text=_MISSING_PROJECT_TEXT
    )

    with pytest.raises(ConnectorValidationError) as excinfo:
        _load(jira_connector_with_invalid_project)

    # Verify the error message is user-friendly
    error_message = str(excinfo.value)
    assert "does not exist" in error_message or "don't have access" in error_message
    assert "INVALID_PROJECT" in error_message or "project" in error_message.lower()


def test_invalid_jql_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Test that an invalid JQL error during indexing is properly handled."""
    mock_source_operations.search_issues.side_effect = JiraApiError(
        "error",
        status_code=400,
        text='{"errorMessages":["Error in the JQL Query: Expecting \')\' before the end of the query."],"errors":{}}',
    )

    with pytest.raises(ConnectorValidationError) as excinfo:
        _load(jira_connector_with_invalid_project)

    # Verify the error message mentions invalid JQL
    error_message = str(excinfo.value)
    assert "Invalid JQL" in error_message or "JQL" in error_message


def test_credential_expired_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Test that expired credentials during indexing are properly handled."""
    mock_source_operations.search_issues.side_effect = JiraApiError(
        "error", status_code=401, text=None
    )

    with pytest.raises(CredentialExpiredError) as excinfo:
        _load(jira_connector_with_invalid_project)

    # Verify the error message mentions credentials
    error_message = str(excinfo.value)
    assert "credential" in error_message.lower() or "401" in error_message


def test_insufficient_permissions_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Test that insufficient permissions during indexing are properly handled."""
    mock_source_operations.search_issues.side_effect = JiraApiError(
        "error", status_code=403, text=None
    )

    with pytest.raises(InsufficientPermissionsError) as excinfo:
        _load(jira_connector_with_invalid_project)

    # Verify the error message mentions permissions
    error_message = str(excinfo.value)
    assert "permission" in error_message.lower() or "403" in error_message


def test_cloud_nonexistent_project_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
    mock_source_operations: MagicMock,
) -> None:
    """Test that a non-existent project error for Jira Cloud is properly handled."""
    mock_source_operations._is_cloud.return_value = True
    mock_source_operations.search_issue_ids.side_effect = JiraApiError(
        "400 Client Error: Bad Request", status_code=400, text=_MISSING_PROJECT_TEXT
    )

    with pytest.raises(ConnectorValidationError) as excinfo:
        _load(jira_connector_with_invalid_project)

    # Verify the error message is user-friendly
    error_message = str(excinfo.value)
    assert "does not exist" in error_message or "don't have access" in error_message
    mock_source_operations.search_issues.assert_not_called()
