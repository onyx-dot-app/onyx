from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from unittest.mock import patch

import pytest

from onyx.federated_connectors.models import OAuthResult
from onyx.federated_connectors.slack.federated_connector import SlackFederatedConnector

# Constants for mock Slack OAuth response
MOCK_APP_ID = "A093M5L7Q92"
MOCK_USER_ID = "U05SAH6UGUD"
MOCK_SCOPE = "search:read"
MOCK_ACCESS_TOKEN = (
    "xoxe.xoxp-1-Mi0yLTU5MTAx...MDkwN2U0YjlmZmI4YzA1NTYwZjNlMjRiZDYwNGU0ZA"
)
MOCK_REFRESH_TOKEN = (
    "xoxe-1-My0xLTU5MTAxMz...jcyZjA3NDM3YjdhOTRhYmRhMGJmMGVlMzBjNzQ4Y2I"
)
MOCK_TOKEN_TYPE = "user"
MOCK_EXPIRES_IN = 31659
MOCK_TEAM_ID = "T05SS40AFAM"
MOCK_TEAM_NAME = "Onyx Team"


class TestSlackFederatedConnector:
    """Test suite for SlackFederatedConnector"""

    @pytest.fixture
    def test_credentials(self) -> dict[str, str]:
        """Test credentials for Slack connector"""
        return {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
            "redirect_uri": "https://test.com/callback",
        }

    @pytest.fixture
    def slack_connector(
        self, test_credentials: dict[str, str]
    ) -> SlackFederatedConnector:
        """Create a SlackFederatedConnector instance for testing"""
        return SlackFederatedConnector(test_credentials)

    @pytest.fixture
    def mock_slack_oauth_response(self) -> dict[str, Any]:
        """Mock Slack OAuth response based on real example"""
        return {
            "ok": True,
            "app_id": MOCK_APP_ID,
            "authed_user": {
                "id": MOCK_USER_ID,
                "scope": MOCK_SCOPE,
                "access_token": MOCK_ACCESS_TOKEN,
                "token_type": MOCK_TOKEN_TYPE,
                "refresh_token": MOCK_REFRESH_TOKEN,
                "expires_in": MOCK_EXPIRES_IN,
            },
            "team": {"id": MOCK_TEAM_ID, "name": MOCK_TEAM_NAME},
            "enterprise": None,
            "is_enterprise_install": False,
        }

    def test_callback_success(
        self,
        slack_connector: SlackFederatedConnector,
        mock_slack_oauth_response: dict[str, Any],
    ) -> None:
        """Test successful OAuth callback handling"""
        # Mock the token exchange method
        with patch.object(
            slack_connector,
            "_exchange_code_for_token",
            return_value=mock_slack_oauth_response,
        ):
            # Simulate callback data with authorization code
            callback_data = {
                "code": "test_auth_code",
                "state": "test_state",
            }
            redirect_uri = "https://test.com/callback"

            # Call the callback method
            result = slack_connector.callback(callback_data, redirect_uri)

            # Assert the result is an OAuthResult
            assert isinstance(result, OAuthResult)

            # Assert OAuth token values are correctly extracted
            assert result.access_token == MOCK_ACCESS_TOKEN
            assert result.refresh_token == MOCK_REFRESH_TOKEN
            assert result.token_type == MOCK_TOKEN_TYPE
            assert result.scope == MOCK_SCOPE

            # Assert expiration time is calculated correctly
            assert result.expires_at is not None
            expected_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=MOCK_EXPIRES_IN
            )
            # Allow for small time difference due to test execution time
            time_diff = abs((result.expires_at - expected_expires_at).total_seconds())
            assert time_diff < 5  # Within 5 seconds

            # Assert team info is extracted correctly
            assert result.team is not None
            assert result.team["id"] == MOCK_TEAM_ID
            assert result.team["name"] == MOCK_TEAM_NAME

            # Assert user info is extracted correctly
            assert result.user is not None
            assert result.user["id"] == MOCK_USER_ID
            assert result.user["scope"] == MOCK_SCOPE
            assert result.user["token_type"] == MOCK_TOKEN_TYPE

            # Assert raw response is preserved
            assert result.raw_response == mock_slack_oauth_response

    def test_callback_oauth_error(
        self, slack_connector: SlackFederatedConnector
    ) -> None:
        """Test OAuth callback with error response"""
        callback_data = {
            "error": "access_denied",
            "error_description": "User denied access",
        }
        redirect_uri = "https://test.com/callback"

        with pytest.raises(RuntimeError, match="OAuth error received: access_denied"):
            slack_connector.callback(callback_data, redirect_uri)

    def test_callback_missing_code(
        self, slack_connector: SlackFederatedConnector
    ) -> None:
        """Test OAuth callback without authorization code"""
        callback_data = {"state": "test_state"}
        redirect_uri = "https://test.com/callback"

        with pytest.raises(ValueError, match="No authorization code received"):
            slack_connector.callback(callback_data, redirect_uri)

    def test_callback_slack_api_error(
        self, slack_connector: SlackFederatedConnector
    ) -> None:
        """Test OAuth callback when Slack API returns error"""
        # Mock failed token exchange
        mock_error_response = {
            "ok": False,
            "error": "invalid_code",
        }

        with patch.object(
            slack_connector,
            "_exchange_code_for_token",
            return_value=mock_error_response,
        ):
            callback_data = {"code": "invalid_code"}
            redirect_uri = "https://test.com/callback"

            with pytest.raises(
                RuntimeError, match="Failed to exchange authorization code for token"
            ):
                slack_connector.callback(callback_data, redirect_uri)

    def test_callback_without_authed_user(
        self, slack_connector: SlackFederatedConnector
    ) -> None:
        """Test OAuth callback when authed_user is missing from response"""
        # Mock response without authed_user
        mock_response = {
            "ok": True,
            "app_id": MOCK_APP_ID,
            "team": {"id": MOCK_TEAM_ID, "name": MOCK_TEAM_NAME},
        }

        with patch.object(
            slack_connector, "_exchange_code_for_token", return_value=mock_response
        ):
            callback_data = {"code": "test_code"}
            redirect_uri = "https://test.com/callback"

            with pytest.raises(
                RuntimeError, match="Missing authed_user in OAuth response from Slack"
            ):
                slack_connector.callback(callback_data, redirect_uri)

    def test_callback_with_incomplete_authed_user(
        self, slack_connector: SlackFederatedConnector
    ) -> None:
        """Test OAuth callback when authed_user is missing access_token"""
        # Mock response with authed_user but missing access_token
        mock_response = {
            "ok": True,
            "app_id": MOCK_APP_ID,
            "authed_user": {
                "id": MOCK_USER_ID,
                "scope": MOCK_SCOPE,
                "token_type": MOCK_TOKEN_TYPE,
                # Missing access_token
            },
            "team": {"id": MOCK_TEAM_ID, "name": MOCK_TEAM_NAME},
        }

        with patch.object(
            slack_connector, "_exchange_code_for_token", return_value=mock_response
        ):
            callback_data = {"code": "test_code"}
            redirect_uri = "https://test.com/callback"

            result = slack_connector.callback(callback_data, redirect_uri)

            # Should handle gracefully - access_token can be None in some edge cases
            assert result.access_token is None
            assert result.refresh_token is None
            assert result.token_type == MOCK_TOKEN_TYPE
            assert result.scope == MOCK_SCOPE
