"""Unit tests for JiraServiceManagementConnector core functionality."""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)
from onyx.connectors.models import ConnectorMissingCredentialError


class TestJiraServiceManagementConnectorInitialization:
    """Test connector initialization and configuration."""

    def test_initialization_with_valid_params(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test connector initialization with valid parameters."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        assert connector.jira_base == jira_base_url
        assert connector.jsm_project_key == jsm_project_key
        assert connector._jira_client is None
        assert connector.labels_to_skip == set()
        assert connector.comment_email_blacklist == ()

    def test_initialization_with_optional_params(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test connector initialization with optional parameters."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
            comment_email_blacklist=["test@example.com", "other@example.com"],
            labels_to_skip=["secret", "confidential"],
            batch_size=100,
            scoped_token=True,
        )

        assert connector.comment_email_blacklist == ("test@example.com", "other@example.com")
        assert connector.labels_to_skip == {"secret", "confidential"}
        assert connector.batch_size == 100
        assert connector.scoped_token is True

    def test_initialization_strips_trailing_slash(self, jsm_project_key: str):
        """Test that trailing slash is stripped from base URL."""
        connector = JiraServiceManagementConnector(
            jira_base_url="https://jira.example.com/",
            jsm_project_key=jsm_project_key,
        )

        assert connector.jira_base == "https://jira.example.com"

    def test_quoted_jsm_project_property(self, jira_base_url: str, jsm_project_key: str):
        """Test that project key is properly quoted."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        assert connector.quoted_jsm_project == f'"{jsm_project_key}"'

    def test_comment_email_blacklist_property(self, jira_base_url: str, jsm_project_key: str):
        """Test comment_email_blacklist property formatting."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
            comment_email_blacklist=["  test@example.com  ", "  other@example.com  "],
        )

        # Should strip whitespace and return tuple
        assert connector.comment_email_blacklist == ("test@example.com", "other@example.com")

    def test_jira_client_property_raises_when_not_set(
        self, jira_base_url: str, jsm_project_key: str
    ):
        """Test that jira_client property raises when credentials not loaded."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        with pytest.raises(ConnectorMissingCredentialError) as exc_info:
            _ = connector.jira_client

        assert "Jira Service Management" in str(exc_info.value)


class TestCredentialLoading:
    """Test credential loading functionality."""

    def test_load_credentials_sets_client(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test that load_credentials sets the Jira client."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        with patch(
            "onyx.connectors.jira_service_management.connector.build_jira_client"
        ) as mock_build:
            mock_build.return_value = mock_jira_client
            result = connector.load_credentials(
                {
                    "jira_user_email": "test@example.com",
                    "jira_api_token": "token123",
                }
            )

        assert connector._jira_client == mock_jira_client
        assert result is None

    def test_load_credentials_with_scoped_token(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test load_credentials with scoped token enabled."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
            scoped_token=True,
        )

        with patch(
            "onyx.connectors.jira_service_management.connector.build_jira_client"
        ) as mock_build:
            mock_build.return_value = mock_jira_client
            connector.load_credentials(
                {
                    "jira_user_email": "test@example.com",
                    "jira_api_token": "token123",
                }
            )

        # Verify scoped_token was passed to build_jira_client
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args[1]
        assert call_kwargs["scoped_token"] is True

    def test_jira_client_property_works_after_load(
        self, jira_base_url: str, jsm_project_key: str, mock_jira_client: MagicMock
    ):
        """Test that jira_client property works after loading credentials."""
        connector = JiraServiceManagementConnector(
            jira_base_url=jira_base_url,
            jsm_project_key=jsm_project_key,
        )

        connector._jira_client = mock_jira_client

        assert connector.jira_client == mock_jira_client
