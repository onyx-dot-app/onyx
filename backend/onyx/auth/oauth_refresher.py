import asyncio
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import cast
from typing import Dict
from typing import List
from typing import Optional

import httpx
from fastapi_users.manager import BaseUserManager
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.configs.app_configs import OAUTH_CLIENT_ID
from onyx.configs.app_configs import OAUTH_CLIENT_SECRET
from onyx.configs.app_configs import OPENID_CONFIG_URL
from onyx.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Standard OAuth refresh token endpoints, keyed by `oauth_account.oauth_name`.
REFRESH_ENDPOINTS: Dict[str, str] = {
    "google": "https://oauth2.googleapis.com/token",
}

# Token endpoint resolved from the configured OIDC discovery document.
# Populated lazily on first successful fetch and re-used thereafter, so the
# .well-known/openid-configuration document is only retrieved once per process.
_OIDC_TOKEN_ENDPOINT_CACHE: Dict[str, str] = {}

# Lazily-initialized lock guarding concurrent first-time fetches of the OIDC
# discovery document. Created on first use so it binds to the running event
# loop rather than at import time.
_OIDC_TOKEN_ENDPOINT_LOCK: Optional[asyncio.Lock] = None


def _get_oidc_lock() -> asyncio.Lock:
    """Return the module-level OIDC discovery lock, creating it on first call."""
    global _OIDC_TOKEN_ENDPOINT_LOCK
    if _OIDC_TOKEN_ENDPOINT_LOCK is None:
        _OIDC_TOKEN_ENDPOINT_LOCK = asyncio.Lock()
    return _OIDC_TOKEN_ENDPOINT_LOCK


async def _get_oidc_token_endpoint() -> Optional[str]:
    """Resolve the OAuth2 token endpoint for the configured OIDC provider.

    Reads `token_endpoint` from the OPENID_CONFIG_URL discovery document so
    refresh works for any OIDC provider (Microsoft Entra, Okta, Keycloak,
    Auth0, ...) without hardcoding provider-specific URLs. The lock + double
    check ensures concurrent callers (e.g. multiple tokens expiring at once
    after a server restart) coalesce into a single discovery request.
    """
    cached = _OIDC_TOKEN_ENDPOINT_CACHE.get("url")
    if cached:
        return cached
    if not OPENID_CONFIG_URL:
        return None
    async with _get_oidc_lock():
        # Re-check inside the lock — another coroutine may have populated
        # the cache while we were waiting to acquire it.
        cached = _OIDC_TOKEN_ENDPOINT_CACHE.get("url")
        if cached:
            return cached
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(OPENID_CONFIG_URL, timeout=10.0)
                response.raise_for_status()
                config: Dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as e:
            # ValueError covers json.JSONDecodeError when the IdP returns a
            # non-JSON body (e.g. an HTML error page from a misconfigured URL).
            logger.warning("Failed to fetch OIDC discovery document: %s", e)
            return None
        token_endpoint = config.get("token_endpoint")
        if isinstance(token_endpoint, str) and token_endpoint:
            _OIDC_TOKEN_ENDPOINT_CACHE["url"] = token_endpoint
            return token_endpoint
        return None


async def _resolve_token_endpoint(provider: str) -> Optional[str]:
    """Return the OAuth2 token endpoint URL for a given provider.

    Falls back to the OIDC discovery document when the provider is "openid"
    (the default name used by httpx_oauth's generic OIDC client) so any
    OIDC-compliant identity provider supports token refresh, not just Google.
    """
    static = REFRESH_ENDPOINTS.get(provider)
    if static:
        return static
    if provider == "openid":
        return await _get_oidc_token_endpoint()
    return None


# NOTE: Keeping this as a utility function for potential future debugging,
# but not using it in production code
async def _test_expire_oauth_token(
    user: User,
    oauth_account: OAuthAccount,
    db_session: AsyncSession,  # noqa: ARG001
    user_manager: BaseUserManager[User, Any],
    expire_in_seconds: int = 10,
) -> bool:
    """
    Utility function for testing - Sets an OAuth token to expire in a short time
    to facilitate testing of the refresh flow.
    Not used in production code.
    """
    try:
        new_expires_at = int(
            (datetime.now(timezone.utc).timestamp() + expire_in_seconds)
        )

        updated_data: Dict[str, Any] = {"expires_at": new_expires_at}

        await user_manager.user_db.update_oauth_account(  # ty: ignore[invalid-argument-type]
            user,  # ty: ignore[invalid-argument-type]
            cast(Any, oauth_account),
            updated_data,
        )

        return True
    except Exception as e:
        logger.exception("Error setting artificial expiration: %s", str(e))
        return False


async def refresh_oauth_token(
    user: User,
    oauth_account: OAuthAccount,
    db_session: AsyncSession,  # noqa: ARG001
    user_manager: BaseUserManager[User, Any],
) -> bool:
    """
    Attempt to refresh an OAuth token that's about to expire or has expired.
    Returns True if successful, False otherwise.
    """
    if not oauth_account.refresh_token:
        logger.warning(
            "No refresh token available for %s's %s account",
            user.email,
            oauth_account.oauth_name,
        )
        return False

    provider = oauth_account.oauth_name
    token_endpoint = await _resolve_token_endpoint(provider)
    if not token_endpoint:
        logger.warning("Refresh endpoint not configured for provider: %s", provider)
        return False

    try:
        logger.info("Refreshing OAuth token for %s's %s account", user.email, provider)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_endpoint,
                data={
                    "client_id": OAUTH_CLIENT_ID,
                    "client_secret": OAUTH_CLIENT_SECRET,
                    "refresh_token": oauth_account.refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if response.status_code != 200:
                logger.error(
                    "Failed to refresh OAuth token: Status %s", response.status_code
                )
                return False

            token_data = response.json()

            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get(
                "refresh_token", oauth_account.refresh_token
            )
            expires_in = token_data.get("expires_in")

            # Calculate new expiry time if provided
            new_expires_at: Optional[int] = None
            if expires_in:
                new_expires_at = int(
                    (datetime.now(timezone.utc).timestamp() + expires_in)
                )

            # Update the OAuth account
            updated_data: Dict[str, Any] = {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
            }

            if new_expires_at:
                updated_data["expires_at"] = new_expires_at

                # Update oidc_expiry in user model if we're tracking it
                if TRACK_EXTERNAL_IDP_EXPIRY:
                    oidc_expiry = datetime.fromtimestamp(
                        new_expires_at, tz=timezone.utc
                    )
                    await user_manager.user_db.update(
                        user, {"oidc_expiry": oidc_expiry}
                    )

            # Update the OAuth account
            await user_manager.user_db.update_oauth_account(  # ty: ignore[invalid-argument-type]
                user,  # ty: ignore[invalid-argument-type]
                cast(Any, oauth_account),
                updated_data,
            )

            logger.info("Successfully refreshed OAuth token for %s", user.email)
            return True

    except Exception as e:
        logger.exception("Error refreshing OAuth token: %s", str(e))
        return False


async def check_and_refresh_oauth_tokens(
    user: User,
    db_session: AsyncSession,
    user_manager: BaseUserManager[User, Any],
) -> None:
    """
    Check if any OAuth tokens are expired or about to expire and refresh them.
    """
    if not hasattr(user, "oauth_accounts") or not user.oauth_accounts:
        return

    now_timestamp = datetime.now(timezone.utc).timestamp()

    # Buffer time to refresh tokens before they expire (in seconds)
    buffer_seconds = 300  # 5 minutes

    for oauth_account in user.oauth_accounts:
        # Skip accounts without refresh tokens
        if not oauth_account.refresh_token:
            continue

        # If token is about to expire, refresh it
        if (
            oauth_account.expires_at
            and oauth_account.expires_at - now_timestamp < buffer_seconds
        ):
            logger.info(
                "OAuth token for %s is about to expire - refreshing", user.email
            )
            success = await refresh_oauth_token(
                user, oauth_account, db_session, user_manager
            )

            if not success:
                logger.warning(
                    "Failed to refresh OAuth token. User may need to re-authenticate."
                )


async def check_oauth_account_has_refresh_token(
    user: User,  # noqa: ARG001
    oauth_account: OAuthAccount,
) -> bool:
    """
    Check if an OAuth account has a refresh token.
    Returns True if a refresh token exists, False otherwise.
    """
    return bool(oauth_account.refresh_token)


async def get_oauth_accounts_requiring_refresh_token(user: User) -> List[OAuthAccount]:
    """
    Returns a list of OAuth accounts for a user that are missing refresh tokens.
    These accounts will need re-authentication to get refresh tokens.
    """
    if not hasattr(user, "oauth_accounts") or not user.oauth_accounts:
        return []

    accounts_needing_refresh = []
    for oauth_account in user.oauth_accounts:
        has_refresh_token = await check_oauth_account_has_refresh_token(
            user, oauth_account
        )
        if not has_refresh_token:
            accounts_needing_refresh.append(oauth_account)

    return accounts_needing_refresh
