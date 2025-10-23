"""
Test suite for OAuthTokenManager.

Tests the OAuth token management functionality including token validation,
refresh, expiration checking, and authorization URL building.
All HTTP requests to external OAuth providers are mocked.
"""

import time
from unittest.mock import Mock
from unittest.mock import patch
from uuid import uuid4

import pytest
from requests import HTTPError
from requests import Response
from sqlalchemy.orm import Session

from onyx.auth.oauth_token_manager import OAuthTokenManager
from onyx.db.models import OAuthConfig
from onyx.db.oauth_config import create_oauth_config
from onyx.db.oauth_config import upsert_user_oauth_token
from tests.external_dependency_unit.conftest import create_test_user


def _create_test_oauth_config(db_session: Session) -> OAuthConfig:
    """Helper to create a test OAuth config"""
    return create_oauth_config(
        name=f"Test OAuth Config {uuid4().hex[:8]}",
        authorization_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        scopes=["repo", "user"],
        additional_params=None,
        db_session=db_session,
    )


class TestOAuthTokenManagerValidation:
    """Tests for token validation and retrieval"""

    def test_get_valid_access_token_with_valid_token(self, db_session: Session) -> None:
        """Test getting a valid access token that hasn't expired"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create a non-expired token
        future_timestamp = int(time.time()) + 3600  # Expires in 1 hour
        token_data = {
            "access_token": "valid_token",
            "refresh_token": "refresh_token",
            "expires_at": future_timestamp,
        }
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Get the token
        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        access_token = manager.get_valid_access_token()

        assert access_token == "valid_token"

    def test_get_valid_access_token_no_token_exists(self, db_session: Session) -> None:
        """Test getting access token when no token exists returns None"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        access_token = manager.get_valid_access_token()

        assert access_token is None

    def test_get_valid_access_token_no_expiration(self, db_session: Session) -> None:
        """Test getting access token without expiration data (assumes valid)"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create token without expiration
        token_data = {
            "access_token": "token_without_expiry",
            "token_type": "Bearer",
        }
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        access_token = manager.get_valid_access_token()

        assert access_token == "token_without_expiry"

    @patch("onyx.auth.oauth_token_manager.requests.post")
    def test_get_valid_access_token_with_expired_token_refreshes(
        self, mock_post: Mock, db_session: Session
    ) -> None:
        """Test that expired token triggers automatic refresh"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create an expired token
        past_timestamp = int(time.time()) - 100  # Expired 100 seconds ago
        token_data = {
            "access_token": "expired_token",
            "refresh_token": "refresh_token",
            "expires_at": past_timestamp,
        }
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Mock the refresh token response
        mock_response = Mock(spec=Response)
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Get the token (should trigger refresh)
        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        access_token = manager.get_valid_access_token()

        assert access_token == "new_access_token"
        # Verify refresh endpoint was called
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == oauth_config.token_url
        assert call_args[1]["data"]["grant_type"] == "refresh_token"
        assert call_args[1]["data"]["refresh_token"] == "refresh_token"

    def test_get_valid_access_token_expired_no_refresh_token(
        self, db_session: Session
    ) -> None:
        """Test that expired token without refresh_token returns None"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create an expired token without refresh_token
        past_timestamp = int(time.time()) - 100
        token_data = {
            "access_token": "expired_token",
            "expires_at": past_timestamp,
            # No refresh_token
        }
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        access_token = manager.get_valid_access_token()

        assert access_token is None

    @patch("onyx.auth.oauth_token_manager.requests.post")
    def test_get_valid_access_token_refresh_fails(
        self, mock_post: Mock, db_session: Session
    ) -> None:
        """Test that failed refresh returns None"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create an expired token
        past_timestamp = int(time.time()) - 100
        token_data = {
            "access_token": "expired_token",
            "refresh_token": "refresh_token",
            "expires_at": past_timestamp,
        }
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Mock the refresh to fail
        mock_post.side_effect = HTTPError("Token refresh failed")

        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        access_token = manager.get_valid_access_token()

        assert access_token is None


class TestOAuthTokenManagerRefresh:
    """Tests for token refresh functionality"""

    @patch("onyx.auth.oauth_token_manager.requests.post")
    def test_refresh_token_success(self, mock_post: Mock, db_session: Session) -> None:
        """Test successful token refresh"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create initial token
        token_data = {
            "access_token": "old_token",
            "refresh_token": "old_refresh",
            "expires_at": int(time.time()) - 100,
        }
        user_token = upsert_user_oauth_token(
            oauth_config.id, user.id, token_data, db_session
        )

        # Mock successful refresh
        new_expires_in = 3600
        mock_response = Mock(spec=Response)
        mock_response.json.return_value = {
            "access_token": "new_token",
            "refresh_token": "new_refresh",
            "expires_in": new_expires_in,
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Refresh the token
        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        new_access_token = manager.refresh_token(user_token)

        assert new_access_token == "new_token"

        # Verify token was updated in DB
        db_session.refresh(user_token)
        assert user_token.token_data["access_token"] == "new_token"
        assert user_token.token_data["refresh_token"] == "new_refresh"
        assert "expires_at" in user_token.token_data

    @patch("onyx.auth.oauth_token_manager.requests.post")
    def test_refresh_token_preserves_refresh_token(
        self, mock_post: Mock, db_session: Session
    ) -> None:
        """Test that refresh preserves old refresh_token if provider doesn't return new one"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create initial token
        token_data = {
            "access_token": "old_token",
            "refresh_token": "old_refresh",
            "expires_at": int(time.time()) - 100,
        }
        user_token = upsert_user_oauth_token(
            oauth_config.id, user.id, token_data, db_session
        )

        # Mock refresh response WITHOUT refresh_token
        mock_response = Mock(spec=Response)
        mock_response.json.return_value = {
            "access_token": "new_token",
            "expires_in": 3600,
            # No refresh_token returned
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        # Refresh the token
        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        manager.refresh_token(user_token)

        # Verify old refresh_token was preserved
        db_session.refresh(user_token)
        assert user_token.token_data["refresh_token"] == "old_refresh"

    @patch("onyx.auth.oauth_token_manager.requests.post")
    def test_refresh_token_http_error(
        self, mock_post: Mock, db_session: Session
    ) -> None:
        """Test that HTTP error during refresh is raised"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        token_data = {
            "access_token": "old_token",
            "refresh_token": "old_refresh",
            "expires_at": int(time.time()) - 100,
        }
        user_token = upsert_user_oauth_token(
            oauth_config.id, user.id, token_data, db_session
        )

        # Mock HTTP error
        mock_response = Mock(spec=Response)
        mock_response.raise_for_status.side_effect = HTTPError("Invalid refresh token")
        mock_post.return_value = mock_response

        manager = OAuthTokenManager(oauth_config, user.id, db_session)

        with pytest.raises(HTTPError):
            manager.refresh_token(user_token)


class TestOAuthTokenManagerExpiration:
    """Tests for token expiration checking"""

    def test_is_token_expired_with_valid_token(self, db_session: Session) -> None:
        """Test that non-expired token is detected as valid"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        manager = OAuthTokenManager(oauth_config, user.id, db_session)

        # Token expires in 2 hours (well beyond 60 second buffer)
        token_data = {"expires_at": int(time.time()) + 7200}

        assert manager.is_token_expired(token_data) is False

    def test_is_token_expired_with_expired_token(self, db_session: Session) -> None:
        """Test that expired token is detected"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        manager = OAuthTokenManager(oauth_config, user.id, db_session)

        # Token expired 1 hour ago
        token_data = {"expires_at": int(time.time()) - 3600}

        assert manager.is_token_expired(token_data) is True

    def test_is_token_expired_with_buffer_zone(self, db_session: Session) -> None:
        """Test that token within 60 second buffer is considered expired"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        manager = OAuthTokenManager(oauth_config, user.id, db_session)

        # Token expires in 30 seconds (within 60 second buffer)
        token_data = {"expires_at": int(time.time()) + 30}

        assert manager.is_token_expired(token_data) is True

    def test_is_token_expired_no_expiration_data(self, db_session: Session) -> None:
        """Test that token without expiration is considered valid"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        manager = OAuthTokenManager(oauth_config, user.id, db_session)

        # Token without expires_at
        token_data = {"access_token": "some_token"}

        assert manager.is_token_expired(token_data) is False


class TestOAuthTokenManagerCodeExchange:
    """Tests for authorization code exchange"""

    @patch("onyx.auth.oauth_token_manager.requests.post")
    def test_exchange_code_for_token_success(
        self, mock_post: Mock, db_session: Session
    ) -> None:
        """Test successful code exchange"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Mock successful token exchange
        mock_response = Mock(spec=Response)
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "repo user",
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        manager = OAuthTokenManager(oauth_config, user.id, db_session)
        token_data = manager.exchange_code_for_token(
            code="auth_code_123", redirect_uri="https://example.com/callback"
        )

        assert token_data["access_token"] == "new_access_token"
        assert token_data["refresh_token"] == "new_refresh_token"
        assert "expires_at" in token_data

        # Verify correct parameters were sent
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == oauth_config.token_url
        assert call_args[1]["data"]["grant_type"] == "authorization_code"
        assert call_args[1]["data"]["code"] == "auth_code_123"
        assert call_args[1]["data"]["client_id"] == oauth_config.client_id
        assert call_args[1]["data"]["client_secret"] == oauth_config.client_secret
        assert call_args[1]["data"]["redirect_uri"] == "https://example.com/callback"

    @patch("onyx.auth.oauth_token_manager.requests.post")
    def test_exchange_code_for_token_http_error(
        self, mock_post: Mock, db_session: Session
    ) -> None:
        """Test that HTTP error during code exchange is raised"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Mock HTTP error
        mock_response = Mock(spec=Response)
        mock_response.raise_for_status.side_effect = HTTPError("Invalid code")
        mock_post.return_value = mock_response

        manager = OAuthTokenManager(oauth_config, user.id, db_session)

        with pytest.raises(HTTPError):
            manager.exchange_code_for_token(
                code="invalid_code", redirect_uri="https://example.com/callback"
            )


class TestOAuthTokenManagerURLBuilding:
    """Tests for authorization URL building"""

    def test_build_authorization_url_basic(self, db_session: Session) -> None:
        """Test building basic authorization URL"""
        oauth_config = _create_test_oauth_config(db_session)

        url = OAuthTokenManager.build_authorization_url(
            oauth_config=oauth_config,
            redirect_uri="https://example.com/callback",
            state="random_state_123",
        )

        assert url.startswith(oauth_config.authorization_url)
        assert "client_id=test_client_id" in url
        assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
        assert "response_type=code" in url
        assert "state=random_state_123" in url
        # Check scopes are included
        assert "scope=repo+user" in url

    def test_build_authorization_url_with_additional_params(
        self, db_session: Session
    ) -> None:
        """Test building URL with additional provider-specific parameters"""
        oauth_config = create_oauth_config(
            name=f"Test OAuth {uuid4().hex[:8]}",
            authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            client_id="google_client_id",
            client_secret="google_client_secret",
            scopes=["email", "profile"],
            additional_params={"access_type": "offline", "prompt": "consent"},
            db_session=db_session,
        )

        url = OAuthTokenManager.build_authorization_url(
            oauth_config=oauth_config,
            redirect_uri="https://example.com/callback",
            state="state_456",
        )

        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "scope=email+profile" in url

    def test_build_authorization_url_no_scopes(self, db_session: Session) -> None:
        """Test building URL when no scopes are configured"""
        oauth_config = create_oauth_config(
            name=f"Test OAuth {uuid4().hex[:8]}",
            authorization_url="https://oauth.example.com/authorize",
            token_url="https://oauth.example.com/token",
            client_id="simple_client_id",
            client_secret="simple_client_secret",
            scopes=None,  # No scopes
            additional_params=None,
            db_session=db_session,
        )

        url = OAuthTokenManager.build_authorization_url(
            oauth_config=oauth_config,
            redirect_uri="https://example.com/callback",
            state="state_789",
        )

        # Should not include scope parameter
        assert "scope=" not in url
        assert "client_id=simple_client_id" in url

    def test_build_authorization_url_with_existing_query_params(
        self, db_session: Session
    ) -> None:
        """Test building URL when authorization_url already has query parameters"""
        oauth_config = create_oauth_config(
            name=f"Test OAuth {uuid4().hex[:8]}",
            authorization_url="https://oauth.example.com/authorize?foo=bar",
            token_url="https://oauth.example.com/token",
            client_id="custom_client_id",
            client_secret="custom_client_secret",
            scopes=["read"],
            additional_params=None,
            db_session=db_session,
        )

        url = OAuthTokenManager.build_authorization_url(
            oauth_config=oauth_config,
            redirect_uri="https://example.com/callback",
            state="state_xyz",
        )

        # Should use & instead of ? since URL already has query params
        assert "foo=bar&" in url or "?foo=bar" in url
        assert "client_id=custom_client_id" in url
