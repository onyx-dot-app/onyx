"""Unit tests for error handling in JSM connector."""

from unittest.mock import MagicMock

import pytest
from jira.exceptions import JIRAError

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


class TestErrorHandling:
    """Test error handling and exception management."""

    def test_error_handling_401(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test error handling for 401 errors."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=401, text="Unauthorized")
        mock_jira_client.project.side_effect = error

        with pytest.raises(CredentialExpiredError):
            connector.validate_connector_settings()

    def test_error_handling_403(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test error handling for 403 errors."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=403, text="Forbidden")
        mock_jira_client.project.side_effect = error

        with pytest.raises(InsufficientPermissionsError):
            connector.validate_connector_settings()

    def test_error_handling_404(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test error handling for 404 errors."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=404, text="Not Found")
        mock_jira_client.project.side_effect = error

        with pytest.raises(ConnectorValidationError) as exc_info:
            connector.validate_connector_settings()

        assert "not found" in str(exc_info.value).lower()

    def test_error_handling_generic(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test error handling for generic errors."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        from onyx.connectors.exceptions import UnexpectedValidationError

        error = Exception("Generic error")
        mock_jira_client.project.side_effect = error

        with pytest.raises(UnexpectedValidationError, match="Unexpected Jira error"):
            connector.validate_connector_settings()

    def test_handle_jira_connector_settings_error_with_text(
        self,
        jira_base_url: str,
        jsm_project_key: str,
        mock_jira_client: MagicMock,
    ):
        """Test _handle_jira_connector_settings_error with error text."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )
        connector._jira_client = mock_jira_client

        error = JIRAError(status_code=500, text="Internal Server Error")
        mock_jira_client.project.side_effect = error

        with pytest.raises(ConnectorValidationError) as exc_info:
            connector.validate_connector_settings()

        assert "Internal Server Error" in str(exc_info.value)
