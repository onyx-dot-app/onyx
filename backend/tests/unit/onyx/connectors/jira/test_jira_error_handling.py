"""Tests for Jira connector error handling during indexing."""

import time
from unittest.mock import MagicMock

import pytest
from jira import JIRA
from jira import JIRAError

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.jira.connector import JiraConnector
from tests.unit.onyx.connectors.utils import load_everything_from_checkpoint_connector


@pytest.fixture
def jira_connector_with_invalid_project(jira_base_url: str) -> JiraConnector:
    """Create a Jira connector with an invalid project key."""
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key="INVALID_PROJECT",
    )
    mock_client = MagicMock(spec=JIRA)
    mock_client._options = {"rest_api_version": "2"}
    connector._jira_client = mock_client
    return connector


def test_nonexistent_project_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
) -> None:
    """Test that a non-existent project error during indexing is properly handled."""
    # Create a JIRAError that mimics the error from the stack trace
    error = JIRAError(
        status_code=400,
        text='{"errorMessages":["The value \'INVALID_PROJECT\' does not exist for the field \'project\'."],"errors":{}}',
    )

    # Mock search_issues to raise this error
    jira_client = jira_connector_with_invalid_project._jira_client
    assert jira_client is not None
    jira_client.search_issues.side_effect = error  # type: ignore

    # Attempt to load from checkpoint - should raise ConnectorValidationError
    end_time = time.time()
    with pytest.raises(ConnectorValidationError) as excinfo:
        list(
            load_everything_from_checkpoint_connector(
                jira_connector_with_invalid_project, 0, end_time
            )
        )

    # Verify the error message is user-friendly
    error_message = str(excinfo.value)
    assert "does not exist" in error_message or "don't have access" in error_message
    assert "INVALID_PROJECT" in error_message or "project" in error_message.lower()


def test_invalid_jql_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
) -> None:
    """Test that an invalid JQL error during indexing is properly handled."""
    # Create a JIRAError for invalid JQL syntax
    error = JIRAError(
        status_code=400,
        text='{"errorMessages":["Error in the JQL Query: Expecting \')\' before the end of the query."],"errors":{}}',
    )

    # Mock search_issues to raise this error
    jira_client = jira_connector_with_invalid_project._jira_client
    assert jira_client is not None
    jira_client.search_issues.side_effect = error  # type: ignore

    # Attempt to load from checkpoint - should raise ConnectorValidationError
    end_time = time.time()
    with pytest.raises(ConnectorValidationError) as excinfo:
        list(
            load_everything_from_checkpoint_connector(
                jira_connector_with_invalid_project, 0, end_time
            )
        )

    # Verify the error message mentions invalid JQL
    error_message = str(excinfo.value)
    assert "Invalid JQL" in error_message or "JQL" in error_message


def test_credential_expired_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
) -> None:
    """Test that expired credentials during indexing are properly handled."""
    # Create a JIRAError for expired credentials
    error = JIRAError(status_code=401)

    # Mock search_issues to raise this error
    jira_client = jira_connector_with_invalid_project._jira_client
    assert jira_client is not None
    jira_client.search_issues.side_effect = error  # type: ignore

    # Attempt to load from checkpoint - should raise CredentialExpiredError
    end_time = time.time()
    with pytest.raises(CredentialExpiredError) as excinfo:
        list(
            load_everything_from_checkpoint_connector(
                jira_connector_with_invalid_project, 0, end_time
            )
        )

    # Verify the error message mentions credentials
    error_message = str(excinfo.value)
    assert "credential" in error_message.lower() or "401" in error_message


def test_insufficient_permissions_error_during_indexing(
    jira_connector_with_invalid_project: JiraConnector,
) -> None:
    """Test that insufficient permissions during indexing are properly handled."""
    # Create a JIRAError for insufficient permissions
    error = JIRAError(status_code=403)

    # Mock search_issues to raise this error
    jira_client = jira_connector_with_invalid_project._jira_client
    assert jira_client is not None
    jira_client.search_issues.side_effect = error  # type: ignore

    # Attempt to load from checkpoint - should raise InsufficientPermissionsError
    end_time = time.time()
    with pytest.raises(InsufficientPermissionsError) as excinfo:
        list(
            load_everything_from_checkpoint_connector(
                jira_connector_with_invalid_project, 0, end_time
            )
        )

    # Verify the error message mentions permissions
    error_message = str(excinfo.value)
    assert "permission" in error_message.lower() or "403" in error_message


def test_cloud_nonexistent_project_error_during_indexing(
    jira_base_url: str,
) -> None:
    """Test that a non-existent project error for Jira Cloud is properly handled."""
    from requests.exceptions import HTTPError

    # Create a cloud connector
    connector = JiraConnector(
        jira_base_url=jira_base_url,
        project_key="INVALID_PROJECT",
    )
    mock_client = MagicMock()
    mock_client._options = {"rest_api_version": "3"}
    connector._jira_client = mock_client

    # Mock the session get method to return an error response
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "errorMessages": [
            "The value 'INVALID_PROJECT' does not exist for the field 'project'."
        ],
        "errors": {},
    }

    # Create a proper HTTPError with the response attached
    http_error = HTTPError("400 Client Error: Bad Request")
    http_error.response = mock_response
    mock_response.raise_for_status.side_effect = http_error

    mock_session = MagicMock()
    mock_session.get.return_value = mock_response
    mock_client._session = mock_session
    mock_client._get_url.return_value = (
        "https://api.atlassian.com/ex/jira/cloud-id/rest/api/3/search/jql"
    )

    # Attempt to load from checkpoint - should raise ConnectorValidationError
    end_time = time.time()
    with pytest.raises(ConnectorValidationError) as excinfo:
        list(load_everything_from_checkpoint_connector(connector, 0, end_time))

    # Verify the error message is user-friendly
    error_message = str(excinfo.value)
    assert "does not exist" in error_message or "don't have access" in error_message
