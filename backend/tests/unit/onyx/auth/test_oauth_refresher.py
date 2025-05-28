from datetime import datetime
from datetime import timezone
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.auth.oauth_refresher import _test_expire_oauth_token
from onyx.auth.oauth_refresher import check_and_refresh_oauth_tokens
from onyx.auth.oauth_refresher import check_oauth_account_has_refresh_token
from onyx.auth.oauth_refresher import get_oauth_accounts_requiring_refresh_token
from onyx.auth.oauth_refresher import refresh_oauth_token
from onyx.db.models import OAuthAccount


@pytest.mark.asyncio
async def test_refresh_oauth_token_success(
    mock_user: MagicMock,
    mock_oauth_account: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> None:
    """Test successful OAuth token refresh."""
    # Mock HTTP client and response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "access_token": "new_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600,
    }

    # Create async mock for the client post method
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    # Use fixture values but ensure refresh token exists
    mock_oauth_account.oauth_name = (
        "google"  # Ensure it's google to match the refresh endpoint
    )
    mock_oauth_account.refresh_token = "old_refresh_token"

    # Patch at the module level where it's actually being used
    with patch("onyx.auth.oauth_refresher.httpx.AsyncClient") as client_class_mock:
        # Configure the context manager
        client_instance = mock_client
        client_class_mock.return_value.__aenter__.return_value = client_instance

        # Call the function under test
        result = await refresh_oauth_token(
            mock_user, mock_oauth_account, mock_db_session, mock_user_manager
        )

    # Assertions
    assert result is True
    mock_client.post.assert_called_once()
    mock_user_manager.user_db.update_oauth_account.assert_called_once()

    # Verify token data was updated correctly
    update_data = mock_user_manager.user_db.update_oauth_account.call_args[0][2]
    assert update_data["access_token"] == "new_token"
    assert update_data["refresh_token"] == "new_refresh_token"
    assert "expires_at" in update_data


@pytest.mark.asyncio
async def test_refresh_oauth_token_failure(
    mock_user: MagicMock,
    mock_oauth_account: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> bool:
    """Test OAuth token refresh failure due to HTTP error."""
    # Mock HTTP client with error response
    mock_response = MagicMock()
    mock_response.status_code = 400  # Simulate error

    # Create async mock for the client post method
    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response

    # Ensure refresh token exists and provider is supported
    mock_oauth_account.oauth_name = "google"
    mock_oauth_account.refresh_token = "old_refresh_token"

    # Patch at the module level where it's actually being used
    with patch("onyx.auth.oauth_refresher.httpx.AsyncClient") as client_class_mock:
        # Configure the context manager
        client_class_mock.return_value.__aenter__.return_value = mock_client

        # Call the function under test
        result = await refresh_oauth_token(
            mock_user, mock_oauth_account, mock_db_session, mock_user_manager
        )

    # Assertions
    assert result is False
    mock_client.post.assert_called_once()
    mock_user_manager.user_db.update_oauth_account.assert_not_called()
    return True


@pytest.mark.asyncio
async def test_refresh_oauth_token_no_refresh_token(
    mock_user: MagicMock,
    mock_oauth_account: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> None:
    """Test OAuth token refresh when no refresh token is available."""
    # Set refresh token to None
    mock_oauth_account.refresh_token = None
    mock_oauth_account.oauth_name = "google"

    # No need to mock httpx since it shouldn't be called
    result = await refresh_oauth_token(
        mock_user, mock_oauth_account, mock_db_session, mock_user_manager
    )

    # Assertions
    assert result is False


@pytest.mark.asyncio
async def test_check_and_refresh_oauth_tokens(
    mock_user: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> None:
    """Test checking and refreshing multiple OAuth tokens."""
    # Create mock user with OAuth accounts
    now_timestamp = datetime.now(timezone.utc).timestamp()

    # Create an account that needs refreshing (expiring soon)
    expiring_account = MagicMock(spec=OAuthAccount)
    expiring_account.oauth_name = "google"
    expiring_account.refresh_token = "refresh_token_1"
    expiring_account.expires_at = now_timestamp + 60  # Expires in 1 minute

    # Create an account that doesn't need refreshing (expires later)
    valid_account = MagicMock(spec=OAuthAccount)
    valid_account.oauth_name = "google"
    valid_account.refresh_token = "refresh_token_2"
    valid_account.expires_at = now_timestamp + 3600  # Expires in 1 hour

    # Create an account without a refresh token
    no_refresh_account = MagicMock(spec=OAuthAccount)
    no_refresh_account.oauth_name = "google"
    no_refresh_account.refresh_token = None
    no_refresh_account.expires_at = (
        now_timestamp + 60
    )  # Expiring soon but no refresh token

    # Set oauth_accounts on the mock user
    mock_user.oauth_accounts = [expiring_account, valid_account, no_refresh_account]

    # Mock refresh_oauth_token function
    with patch(
        "onyx.auth.oauth_refresher.refresh_oauth_token", AsyncMock(return_value=True)
    ) as mock_refresh:
        # Call the function under test
        await check_and_refresh_oauth_tokens(
            mock_user, mock_db_session, mock_user_manager
        )

    # Assertions
    assert mock_refresh.call_count == 1  # Should only refresh the expiring account
    # Check it was called with the expiring account
    mock_refresh.assert_called_once_with(
        mock_user, expiring_account, mock_db_session, mock_user_manager
    )


@pytest.mark.asyncio
async def test_get_oauth_accounts_requiring_refresh_token(mock_user: MagicMock) -> None:
    """Test identifying OAuth accounts that need refresh tokens."""
    # Create accounts with and without refresh tokens
    account_with_token = MagicMock(spec=OAuthAccount)
    account_with_token.oauth_name = "google"
    account_with_token.refresh_token = "refresh_token"

    account_without_token = MagicMock(spec=OAuthAccount)
    account_without_token.oauth_name = "google"
    account_without_token.refresh_token = None

    second_account_without_token = MagicMock(spec=OAuthAccount)
    second_account_without_token.oauth_name = "github"
    second_account_without_token.refresh_token = (
        ""  # Empty string should also be treated as missing
    )

    # Set accounts on user
    mock_user.oauth_accounts = [
        account_with_token,
        account_without_token,
        second_account_without_token,
    ]

    # Call the function under test
    accounts_needing_refresh = await get_oauth_accounts_requiring_refresh_token(
        mock_user
    )

    # Assertions
    assert len(accounts_needing_refresh) == 2
    assert account_without_token in accounts_needing_refresh
    assert second_account_without_token in accounts_needing_refresh
    assert account_with_token not in accounts_needing_refresh


@pytest.mark.asyncio
async def test_check_oauth_account_has_refresh_token(
    mock_user: MagicMock, mock_oauth_account: MagicMock
) -> None:
    """Test checking if an OAuth account has a refresh token."""
    # Test with refresh token
    mock_oauth_account.refresh_token = "refresh_token"
    has_token = await check_oauth_account_has_refresh_token(
        mock_user, mock_oauth_account
    )
    assert has_token is True

    # Test with None refresh token
    mock_oauth_account.refresh_token = None
    has_token = await check_oauth_account_has_refresh_token(
        mock_user, mock_oauth_account
    )
    assert has_token is False

    # Test with empty string refresh token
    mock_oauth_account.refresh_token = ""
    has_token = await check_oauth_account_has_refresh_token(
        mock_user, mock_oauth_account
    )
    assert has_token is False


@pytest.mark.asyncio
async def test_test_expire_oauth_token(
    mock_user: MagicMock,
    mock_oauth_account: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> None:
    """Test the testing utility function for token expiration."""
    # Set up the mock account
    mock_oauth_account.oauth_name = "google"
    mock_oauth_account.refresh_token = "test_refresh_token"
    mock_oauth_account.access_token = "test_access_token"

    # Call the function under test
    result = await _test_expire_oauth_token(
        mock_user,
        mock_oauth_account,
        mock_db_session,
        mock_user_manager,
        expire_in_seconds=10,
    )

    # Assertions
    assert result is True
    mock_user_manager.user_db.update_oauth_account.assert_called_once()

    # Verify the expiration time was set correctly
    update_data = mock_user_manager.user_db.update_oauth_account.call_args[0][2]
    assert "expires_at" in update_data

    # Now should be within 10-11 seconds of the set expiration
    now = datetime.now(timezone.utc).timestamp()
    assert update_data["expires_at"] - now >= 8.9  # Allow 1 second for test execution
    assert update_data["expires_at"] - now <= 11.1  # Allow 1 second for test execution
