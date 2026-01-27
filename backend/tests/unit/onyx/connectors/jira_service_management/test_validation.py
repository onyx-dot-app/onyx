"""Unit tests for connector validation."""

from unittest.mock import MagicMock

import pytest
from jira.exceptions import JIRAError

from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestConnectorValidation:
    """Test connector settings validation."""

    def test_validate_raises_when_no_credentials(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that validation raises when credentials not loaded."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            connector.validate_connector_settings()

        assert "Jira Service Management" in str(exc_info.value)

    def test_validate_with_valid_project(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test validation with valid project."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        # Mock successful project retrieval
        mock_project = MagicMock()
        mock_project.key = jsm_project_key
        mock_project.name = "IT Service Management"
        mock_jira_client.project.return_value = mock_project

        # Should not raise
        connector.validate_connector_settings()

        mock_jira_client.project.assert_called_once_with(jsm_project_key)

    def test_validate_handles_401_error(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test validation handles 401 (expired credentials) error."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=401, text="Unauthorized")
        mock_jira_client.project.side_effect = error

        with pytest.raises(CredentialExpiredError) as exc_info:
            connector.validate_connector_settings()

        assert "expired or invalid" in str(exc_info.value).lower()

    def test_validate_handles_403_error(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test validation handles 403 (insufficient permissions) error."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=403, text="Forbidden")
        mock_jira_client.project.side_effect = error

        with pytest.raises(InsufficientPermissionsError) as exc_info:
            connector.validate_connector_settings()

        assert jsm_project_key in str(exc_info.value)
        assert "permissions" in str(exc_info.value).lower()

    def test_validate_handles_404_error(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test validation handles 404 (project not found) error."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=404, text="Not Found")
        mock_jira_client.project.side_effect = error

        with pytest.raises(ConnectorValidationError) as exc_info:
            connector.validate_connector_settings()

        assert jsm_project_key in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    def test_validate_handles_429_error(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test validation handles 429 (rate limit) error."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=429, text="Too Many Requests")
        mock_jira_client.project.side_effect = error

        with pytest.raises(ConnectorValidationError) as exc_info:
            connector.validate_connector_settings()

        assert "rate-limit" in str(exc_info.value).lower()
