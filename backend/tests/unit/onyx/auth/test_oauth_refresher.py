from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.auth import oauth_refresher
from onyx.auth.oauth_refresher import (
    _resolve_refresh_context,
    _resolve_token_endpoint,
    _test_expire_oauth_token,
    check_and_refresh_oauth_tokens,
    check_oauth_account_has_refresh_token,
    get_oauth_accounts_requiring_refresh_token,
    refresh_oauth_token,
)
from onyx.db.enums import SSOProviderType
from onyx.db.models import OAuthAccount
from onyx.utils.sensitive import make_mock_sensitive_value

_ENV_DISCOVERY_URL = "https://idp.example.com/.well-known/openid-configuration"


@pytest.fixture
def legacy_env_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """No provider row resolves and the legacy env credentials are set."""
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_ID", "env-cid")
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_SECRET", "env-secret")


def _provider_row(provider_type: SSOProviderType, config: dict[str, str]) -> MagicMock:
    provider = MagicMock()
    provider.provider_type = provider_type
    provider.config = make_mock_sensitive_value(config)
    return provider


@pytest.mark.asyncio
@pytest.mark.usefixtures("legacy_env_mode")
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
@pytest.mark.usefixtures("legacy_env_mode")
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
async def test_check_and_refresh_oauth_tokens_coalesces_concurrent_refresh(
    mock_user_manager: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent refreshes for the same user trigger only one IdP POST.

    Mirrors the post-refresh in-memory state by having the mocked
    `refresh_oauth_token` update `account.expires_at` to a fresh value
    (the way `update_oauth_account` would refresh the SQLAlchemy object on
    success). The second coroutine must observe the fresh `expires_at`
    inside the per-user lock and skip its redundant POST.
    """
    import asyncio as _asyncio

    monkeypatch.setattr(oauth_refresher, "_USER_REFRESH_LOCKS", {})
    monkeypatch.setattr(oauth_refresher, "_USER_REFRESH_LOCKS_GUARD", None)

    now_timestamp = datetime.now(timezone.utc).timestamp()

    account = MagicMock(spec=OAuthAccount)
    account.oauth_name = "openid"
    account.refresh_token = "rt"
    account.expires_at = now_timestamp + 60  # within renewal buffer

    user = MagicMock()
    user.id = "concurrent-test-user"
    user.email = "concurrent@example.com"
    user.oauth_accounts = [account]

    db_session = MagicMock()
    db_session.refresh = AsyncMock()

    refresh_started = _asyncio.Event()
    release_refresh = _asyncio.Event()

    async def slow_refresh(
        _u: MagicMock, a: MagicMock, *_args: object, **_kwargs: object
    ) -> bool:
        # Park the first caller inside refresh_oauth_token so the second
        # caller has a chance to reach the lock; the test fails
        # (call_count > 1) if the lock doesn't coalesce them.
        refresh_started.set()
        await release_refresh.wait()
        a.expires_at = now_timestamp + 3600  # simulate post-refresh state
        return True

    with patch(
        "onyx.auth.oauth_refresher.refresh_oauth_token",
        AsyncMock(side_effect=slow_refresh),
    ) as mock_refresh:
        first = _asyncio.create_task(
            check_and_refresh_oauth_tokens(user, db_session, mock_user_manager)
        )
        await refresh_started.wait()
        second = _asyncio.create_task(
            check_and_refresh_oauth_tokens(user, db_session, mock_user_manager)
        )
        # Yield once so the second task reaches the lock acquisition.
        await _asyncio.sleep(0)
        release_refresh.set()
        await _asyncio.gather(first, second)

    assert mock_refresh.call_count == 1


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
async def test_resolve_token_endpoint_google_static(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Static provider URLs (e.g. Google) bypass discovery."""
    # Clear discovery cache so a misbehaving fallback would surface as a fetch.
    monkeypatch.setattr(oauth_refresher, "_OIDC_TOKEN_ENDPOINT_CACHE", {})
    endpoint = await _resolve_token_endpoint("google")
    assert endpoint == "https://oauth2.googleapis.com/token"


@pytest.mark.asyncio
async def test_resolve_token_endpoint_openid_via_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For OIDC ("openid"), the token endpoint is read from the discovery doc."""
    monkeypatch.setattr(oauth_refresher, "_OIDC_TOKEN_ENDPOINT_CACHE", {})
    # Reset the locks so they get created in the current test's event loop;
    # without this, a prior test's lock could be bound to a different loop.
    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS", {})
    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS_GUARD", None)
    monkeypatch.setattr(
        oauth_refresher,
        "OPENID_CONFIG_URL",
        "https://idp.example.com/.well-known/openid-configuration",
    )

    discovery_response = MagicMock()
    discovery_response.status_code = 200
    discovery_response.json.return_value = {
        "token_endpoint": "https://idp.example.com/oauth2/v2.0/token",
    }
    discovery_response.raise_for_status.return_value = None

    mock_client = AsyncMock()
    mock_client.get.return_value = discovery_response

    with patch("onyx.auth.oauth_refresher.httpx.AsyncClient") as client_class_mock:
        client_class_mock.return_value.__aenter__.return_value = mock_client
        endpoint = await _resolve_token_endpoint("openid")

    assert endpoint == "https://idp.example.com/oauth2/v2.0/token"
    # Cached after first successful fetch, keyed by discovery URL.
    cached_entry = oauth_refresher._OIDC_TOKEN_ENDPOINT_CACHE.get(
        "https://idp.example.com/.well-known/openid-configuration"
    )
    assert cached_entry is not None
    assert cached_entry[0] == "https://idp.example.com/oauth2/v2.0/token"

    # Subsequent calls do not re-fetch the discovery document.
    mock_client.get.reset_mock()
    endpoint_cached = await _resolve_token_endpoint("openid")
    assert endpoint_cached == "https://idp.example.com/oauth2/v2.0/token"
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_token_endpoint_openid_cache_ttl_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired cache entry triggers a fresh discovery fetch."""
    import time as _time

    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS", {})
    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS_GUARD", None)
    monkeypatch.setattr(
        oauth_refresher,
        "OPENID_CONFIG_URL",
        "https://idp.example.com/.well-known/openid-configuration",
    )
    monkeypatch.setattr(oauth_refresher, "OIDC_DISCOVERY_CACHE_TTL_SECONDS", 1)
    # Pre-populate the cache with an entry that's already past TTL.
    expired_fetched_at = _time.monotonic() - 60.0
    monkeypatch.setattr(
        oauth_refresher,
        "_OIDC_TOKEN_ENDPOINT_CACHE",
        {
            "https://idp.example.com/.well-known/openid-configuration": (
                "https://idp.example.com/old-token-endpoint",
                expired_fetched_at,
            ),
        },
    )

    discovery_response = MagicMock()
    discovery_response.status_code = 200
    discovery_response.raise_for_status.return_value = None
    discovery_response.json.return_value = {
        "token_endpoint": "https://idp.example.com/new-token-endpoint",
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = discovery_response

    with patch("onyx.auth.oauth_refresher.httpx.AsyncClient") as client_class_mock:
        client_class_mock.return_value.__aenter__.return_value = mock_client
        endpoint = await _resolve_token_endpoint("openid")

    # Must NOT return the stale cached URL; a fresh fetch is required.
    assert endpoint == "https://idp.example.com/new-token-endpoint"
    mock_client.get.assert_called_once()


@pytest.mark.asyncio
async def test_resolve_token_endpoint_openid_no_config_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without OPENID_CONFIG_URL configured, "openid" resolves to None."""
    monkeypatch.setattr(oauth_refresher, "_OIDC_TOKEN_ENDPOINT_CACHE", {})
    monkeypatch.setattr(oauth_refresher, "OPENID_CONFIG_URL", "")
    endpoint = await _resolve_token_endpoint("openid")
    assert endpoint is None


@pytest.mark.asyncio
async def test_resolve_token_endpoint_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown providers return None and trigger no network calls."""
    monkeypatch.setattr(oauth_refresher, "_OIDC_TOKEN_ENDPOINT_CACHE", {})
    endpoint = await _resolve_token_endpoint("github")
    assert endpoint is None


@pytest.mark.asyncio
async def test_resolve_token_endpoint_openid_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-JSON discovery body degrades to None instead of crashing."""
    monkeypatch.setattr(oauth_refresher, "_OIDC_TOKEN_ENDPOINT_CACHE", {})
    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS", {})
    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS_GUARD", None)
    monkeypatch.setattr(
        oauth_refresher,
        "OPENID_CONFIG_URL",
        "https://idp.example.com/.well-known/openid-configuration",
    )

    discovery_response = MagicMock()
    discovery_response.status_code = 200
    discovery_response.raise_for_status.return_value = None
    # Simulate an HTML error page or any non-JSON body.
    discovery_response.json.side_effect = ValueError("not valid JSON")

    mock_client = AsyncMock()
    mock_client.get.return_value = discovery_response

    with patch("onyx.auth.oauth_refresher.httpx.AsyncClient") as client_class_mock:
        client_class_mock.return_value.__aenter__.return_value = mock_client
        endpoint = await _resolve_token_endpoint("openid")

    assert endpoint is None
    # The failure is negative-cached so a hard-down IdP is not re-fetched on
    # every request within the (short) negative TTL.
    entry = oauth_refresher._OIDC_TOKEN_ENDPOINT_CACHE.get(
        "https://idp.example.com/.well-known/openid-configuration"
    )
    assert entry is not None and entry[0] is None
    mock_client.get.reset_mock()
    endpoint_again = await _resolve_token_endpoint("openid")
    assert endpoint_again is None
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_token_endpoint_openid_concurrent_fetches_coalesce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent callers must trigger only one discovery request."""
    import asyncio as _asyncio

    monkeypatch.setattr(oauth_refresher, "_OIDC_TOKEN_ENDPOINT_CACHE", {})
    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS", {})
    monkeypatch.setattr(oauth_refresher, "_OIDC_DISCOVERY_LOCKS_GUARD", None)
    monkeypatch.setattr(
        oauth_refresher,
        "OPENID_CONFIG_URL",
        "https://idp.example.com/.well-known/openid-configuration",
    )

    fetch_started = _asyncio.Event()
    release_fetch = _asyncio.Event()

    async def slow_get(*_args: object, **_kwargs: object) -> MagicMock:
        # Park the first caller inside the discovery fetch so subsequent
        # callers must wait on the lock; the test fails (call_count > 1) if
        # they slip past the lock and fire their own fetch.
        fetch_started.set()
        await release_fetch.wait()
        response = MagicMock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "token_endpoint": "https://idp.example.com/oauth2/v2.0/token",
        }
        return response

    mock_client = AsyncMock()
    mock_client.get.side_effect = slow_get

    with patch("onyx.auth.oauth_refresher.httpx.AsyncClient") as client_class_mock:
        client_class_mock.return_value.__aenter__.return_value = mock_client

        first = _asyncio.create_task(_resolve_token_endpoint("openid"))
        await fetch_started.wait()
        # Second + third callers must block on the lock until `first` finishes.
        second = _asyncio.create_task(_resolve_token_endpoint("openid"))
        third = _asyncio.create_task(_resolve_token_endpoint("openid"))
        # Yield control so the queued tasks reach the lock.
        await _asyncio.sleep(0)
        release_fetch.set()
        results = await _asyncio.gather(first, second, third)

    assert all(r == "https://idp.example.com/oauth2/v2.0/token" for r in results)
    assert mock_client.get.call_count == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("legacy_env_mode")
async def test_refresh_oauth_token_openid_provider(
    mock_user: MagicMock,
    mock_oauth_account: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OIDC ("openid") accounts refresh via the discovery-resolved endpoint."""
    import time as _time

    # Pre-populate the cache so the refresh test does not depend on the
    # discovery-doc fetch path (covered separately above). Include a fresh
    # `fetched_at` so the entry is well within the TTL window.
    monkeypatch.setattr(
        oauth_refresher,
        "_OIDC_TOKEN_ENDPOINT_CACHE",
        {
            _ENV_DISCOVERY_URL: (
                "https://idp.example.com/oauth2/v2.0/token",
                _time.monotonic(),
            ),
        },
    )
    monkeypatch.setattr(oauth_refresher, "OPENID_CONFIG_URL", _ENV_DISCOVERY_URL)

    mock_oauth_account.oauth_name = "openid"
    mock_oauth_account.refresh_token = "old_refresh_token"

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = {
        "access_token": "new_token",
        "refresh_token": "new_refresh_token",
        "expires_in": 3600,
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = token_response

    with patch("onyx.auth.oauth_refresher.httpx.AsyncClient") as client_class_mock:
        client_class_mock.return_value.__aenter__.return_value = mock_client
        result = await refresh_oauth_token(
            mock_user, mock_oauth_account, mock_db_session, mock_user_manager
        )

    assert result is True
    mock_client.post.assert_called_once()
    posted_url = mock_client.post.call_args[0][0]
    assert posted_url == "https://idp.example.com/oauth2/v2.0/token"
    mock_user_manager.user_db.update_oauth_account.assert_called_once()


@pytest.mark.asyncio
async def test_expire_oauth_token(
    mock_user: MagicMock,
    mock_oauth_account: MagicMock,
    mock_user_manager: MagicMock,
    mock_db_session: AsyncSession,
) -> None:
    """Tests the testing utility function for token expiration."""
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
    assert update_data["expires_at"] - now >= 8.8  # Allow ~1 second for test execution
    assert update_data["expires_at"] - now <= 11.2  # Allow ~1 second for test execution


@pytest.mark.asyncio
async def test_resolve_context_from_oidc_provider_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An account named after an OIDC provider row refreshes with that row's
    credentials and its discovery-resolved endpoint, whatever the row's name."""
    import time as _time

    row = _provider_row(
        SSOProviderType.OIDC,
        {
            "client_id": "row-cid",
            "client_secret": "row-secret",
            "openid_config_url": "https://keycloak.example.com/.well-known/openid-configuration",
        },
    )
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(
        oauth_refresher,
        "_OIDC_TOKEN_ENDPOINT_CACHE",
        {
            "https://keycloak.example.com/.well-known/openid-configuration": (
                "https://keycloak.example.com/token",
                _time.monotonic(),
            ),
        },
    )
    # Env creds absent: the row must be sufficient on its own.
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_SECRET", "")

    context = await _resolve_refresh_context(MagicMock(), "keycloak")
    assert context is not None
    assert context.token_endpoint == "https://keycloak.example.com/token"
    assert context.client_id == "row-cid"
    assert context.client_secret == "row-secret"


@pytest.mark.asyncio
async def test_resolve_context_from_google_provider_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Google rows use the static Google token endpoint with row credentials."""
    row = _provider_row(
        SSOProviderType.GOOGLE_OAUTH,
        {"client_id": "g-cid", "client_secret": "g-secret"},
    )
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_SECRET", "")

    context = await _resolve_refresh_context(MagicMock(), "google")
    assert context is not None
    assert context.token_endpoint == "https://oauth2.googleapis.com/token"
    assert context.client_id == "g-cid"
    assert context.client_secret == "g-secret"


@pytest.mark.asyncio
async def test_resolve_context_row_lookup_failure_rolls_back_and_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed lookup may have aborted the shared transaction, so the session
    is rolled back and this refresh is skipped rather than POSTing a refresh
    whose result could not be persisted."""
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(side_effect=RuntimeError("db down")),
    )
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_ID", "env-cid")
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_SECRET", "env-secret")

    session = MagicMock()
    session.rollback = AsyncMock()
    context = await _resolve_refresh_context(session, "google")
    assert context is None
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_resolve_context_no_row_unknown_name_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a row, names outside the legacy set have no refresh path."""
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(return_value=None),
    )
    context = await _resolve_refresh_context(MagicMock(), "keycloak")
    assert context is None


@pytest.mark.asyncio
async def test_resolve_context_env_without_credentials_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The legacy path refuses to POST empty credentials to the IdP."""
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_SECRET", "")

    context = await _resolve_refresh_context(MagicMock(), "google")
    assert context is None


@pytest.mark.asyncio
async def test_resolve_context_unreadable_row_config_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row whose config cannot be decrypted disables refresh for its
    accounts instead of falling back to env credentials or raising."""
    row = MagicMock()
    row.provider_type = SSOProviderType.OIDC
    row.config = MagicMock()
    row.config.get_value.side_effect = ValueError("bad key")
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(return_value=row),
    )
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_ID", "env-cid")
    monkeypatch.setattr(oauth_refresher, "OAUTH_CLIENT_SECRET", "env-secret")

    context = await _resolve_refresh_context(MagicMock(), "keycloak")
    assert context is None


@pytest.mark.asyncio
async def test_resolve_context_null_row_config_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row whose config decrypts to None resolves like an empty config
    (missing credentials) instead of raising AttributeError."""
    row = MagicMock()
    row.provider_type = SSOProviderType.OIDC
    row.config = MagicMock()
    row.config.get_value.return_value = None
    monkeypatch.setattr(
        oauth_refresher,
        "fetch_sso_provider_by_name_async",
        AsyncMock(return_value=row),
    )

    context = await _resolve_refresh_context(MagicMock(), "keycloak")
    assert context is None
