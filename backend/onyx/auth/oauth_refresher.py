import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast

import httpx
from fastapi_users.manager import BaseUserManager
from sqlalchemy.ext.asyncio import AsyncSession

from onyx.configs.app_configs import (
    OAUTH_CLIENT_ID,
    OAUTH_CLIENT_SECRET,
    OPENID_CONFIG_URL,
)
from onyx.db.enums import SSOProviderType
from onyx.db.models import OAuthAccount, User
from onyx.db.sso_provider import fetch_sso_provider_by_name_async
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger

logger = setup_logger()

GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Legacy env-credential refresh endpoints, keyed by oauth_account.oauth_name.
REFRESH_ENDPOINTS: Dict[str, str] = {
    "google": GOOGLE_TOKEN_ENDPOINT,
}

# Token endpoints from OIDC discovery, keyed by discovery URL. A None entry
# negative-caches a failed fetch (short TTL) so a hard-down IdP is not re-tried
# per request. Positive entries re-fetch after the long TTL (endpoint rotation).
_OIDC_TOKEN_ENDPOINT_CACHE: Dict[str, tuple[Optional[str], float]] = {}

# Default 1 hour: matches Microsoft Entra's default access-token lifetime, so
# at worst one refresh fails after an endpoint rotation before we self-heal.
OIDC_DISCOVERY_CACHE_TTL_SECONDS: int = int(
    os.environ.get("OIDC_DISCOVERY_CACHE_TTL_SECONDS") or 3600
)

# Negative entries retry quickly so a transient IdP outage self-heals fast.
OIDC_DISCOVERY_NEGATIVE_TTL_SECONDS: int = 45

# Per-discovery-URL locks so one IdP's hanging fetch never blocks another's.
# Created on first use so they bind to the running event loop.
_OIDC_DISCOVERY_LOCKS: Dict[str, asyncio.Lock] = {}
_OIDC_DISCOVERY_LOCKS_GUARD: Optional[asyncio.Lock] = None


def _get_discovery_locks_guard() -> asyncio.Lock:
    """Lazy-init the meta-lock that protects the per-URL lock dict itself."""
    global _OIDC_DISCOVERY_LOCKS_GUARD
    if _OIDC_DISCOVERY_LOCKS_GUARD is None:
        _OIDC_DISCOVERY_LOCKS_GUARD = asyncio.Lock()
    return _OIDC_DISCOVERY_LOCKS_GUARD


async def _get_discovery_lock(config_url: str) -> asyncio.Lock:
    """Get-or-create the discovery lock for one discovery URL."""
    async with _get_discovery_locks_guard():
        lock = _OIDC_DISCOVERY_LOCKS.get(config_url)
        if lock is None:
            lock = asyncio.Lock()
            _OIDC_DISCOVERY_LOCKS[config_url] = lock
        return lock


# Per-user locks coalescing concurrent token-refresh attempts. Without this,
# two requests for the same user near expiry could both POST a refresh, and
# IdPs that rotate refresh tokens (e.g. Microsoft Entra) would invalidate one
# of them with `400 invalid_grant`. The lock pairs with a re-read inside
# `check_and_refresh_oauth_tokens` so the second coroutine skips the redundant
# request entirely once the first has succeeded.
_USER_REFRESH_LOCKS: Dict[uuid.UUID, asyncio.Lock] = {}
_USER_REFRESH_LOCKS_GUARD: Optional[asyncio.Lock] = None


def _get_user_refresh_locks_guard() -> asyncio.Lock:
    """Lazy-init the meta-lock that protects the per-user lock dict itself."""
    global _USER_REFRESH_LOCKS_GUARD
    if _USER_REFRESH_LOCKS_GUARD is None:
        _USER_REFRESH_LOCKS_GUARD = asyncio.Lock()
    return _USER_REFRESH_LOCKS_GUARD


async def _get_user_refresh_lock(user_id: uuid.UUID) -> asyncio.Lock:
    """Get-or-create a per-user lock keyed by `user.id`."""
    async with _get_user_refresh_locks_guard():
        lock = _USER_REFRESH_LOCKS.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _USER_REFRESH_LOCKS[user_id] = lock
        return lock


def _cached_token_endpoint(config_url: str) -> tuple[bool, Optional[str]]:
    """(hit, endpoint) for a URL. A hit with None is a live negative entry."""
    entry = _OIDC_TOKEN_ENDPOINT_CACHE.get(config_url)
    if entry is None:
        return False, None
    endpoint, fetched_at = entry
    ttl = (
        OIDC_DISCOVERY_CACHE_TTL_SECONDS
        if endpoint
        else OIDC_DISCOVERY_NEGATIVE_TTL_SECONDS
    )
    if (time.monotonic() - fetched_at) >= ttl:
        return False, None
    return True, endpoint


async def _get_oidc_token_endpoint(config_url: str) -> Optional[str]:
    """Resolve token_endpoint from an OIDC discovery document. The per-URL
    lock + double check coalesce concurrent fetches into one request."""
    if not config_url:
        return None
    hit, cached = _cached_token_endpoint(config_url)
    if hit:
        return cached
    async with await _get_discovery_lock(config_url):
        # Re-check inside the lock — another coroutine may have populated
        # the cache while we were waiting to acquire it.
        hit, cached = _cached_token_endpoint(config_url)
        if hit:
            return cached
        token_endpoint: Optional[str] = None
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(config_url, timeout=10.0)
                response.raise_for_status()
                config: Dict[str, Any] = response.json()
            raw_endpoint = config.get("token_endpoint")
            if isinstance(raw_endpoint, str) and raw_endpoint:
                token_endpoint = raw_endpoint
        except (httpx.HTTPError, ValueError) as e:
            # ValueError covers json.JSONDecodeError when the IdP returns a
            # non-JSON body (e.g. an HTML error page from a misconfigured URL).
            logger.warning("Failed to fetch OIDC discovery document: %s", e)
        _OIDC_TOKEN_ENDPOINT_CACHE[config_url] = (token_endpoint, time.monotonic())
        return token_endpoint


async def _resolve_token_endpoint(provider: str) -> Optional[str]:
    """Legacy env-credential resolution for accounts with no provider row:
    "openid" resolves via the env discovery URL, other names are static."""
    static = REFRESH_ENDPOINTS.get(provider)
    if static:
        return static
    if provider == "openid":
        return await _get_oidc_token_endpoint(OPENID_CONFIG_URL)
    return None


@dataclass(frozen=True)
class _RefreshContext:
    token_endpoint: str
    client_id: str
    # repr=False keeps the secret out of any future log/repr of the context.
    client_secret: str = field(repr=False)


async def _resolve_refresh_context(
    db_session: AsyncSession, oauth_name: str
) -> Optional[_RefreshContext]:
    """Endpoint + client credentials for an account: the provider row matching
    oauth_name wins, rowless accounts fall back to the legacy env config."""
    try:
        provider = await fetch_sso_provider_by_name_async(db_session, oauth_name)
    except Exception:
        # A failed lookup may have aborted the shared transaction that later
        # persists the token: roll back and skip, or a rotating IdP's fresh
        # refresh token would be minted and then lost.
        logger.exception(
            "SSO provider lookup failed for %s; skipping token refresh", oauth_name
        )
        try:
            await db_session.rollback()
        except Exception:
            logger.exception("Session rollback failed after provider lookup error")
        return None

    if provider is not None and provider.provider_type is not SSOProviderType.SAML:
        try:
            raw_config = (
                provider.config.get_value(apply_mask=False) if provider.config else None
            )
            config: Dict[str, Any] = raw_config or {}
        except Exception:
            # Never fall back to env creds (a different app registration).
            logger.exception(
                "Could not read SSO provider %s config (re-encryption needed after "
                "a key rotation?); token refresh disabled for its accounts",
                oauth_name,
            )
            return None
        client_id = config.get("client_id") or ""
        client_secret = config.get("client_secret") or ""
        endpoint = (
            GOOGLE_TOKEN_ENDPOINT
            if provider.provider_type is SSOProviderType.GOOGLE_OAUTH
            else await _get_oidc_token_endpoint(config.get("openid_config_url") or "")
        )
        if endpoint and client_id and client_secret:
            return _RefreshContext(endpoint, client_id, client_secret)
        logger.error(
            "SSO provider %s cannot refresh tokens: has_endpoint=%s "
            "has_client_id=%s has_client_secret=%s",
            oauth_name,
            bool(endpoint),
            bool(client_id),
            bool(client_secret),
        )
        return None

    endpoint = await _resolve_token_endpoint(oauth_name)
    if not endpoint:
        logger.warning("Refresh endpoint not configured for provider: %s", oauth_name)
        return None
    if not OAUTH_CLIENT_ID or not OAUTH_CLIENT_SECRET:
        logger.error(
            "No OAuth credentials configured to refresh provider: %s", oauth_name
        )
        return None
    return _RefreshContext(endpoint, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET)


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
    db_session: AsyncSession,
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
    context = await _resolve_refresh_context(db_session, provider)
    if context is None:
        return False

    try:
        logger.info("Refreshing OAuth token for %s's %s account", user.email, provider)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                context.token_endpoint,
                data={
                    "client_id": context.client_id,
                    "client_secret": context.client_secret,
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

                if get_security_settings().track_external_idp_expiry:
                    oidc_expiry = datetime.fromtimestamp(
                        new_expires_at, tz=timezone.utc
                    )
                    await user_manager.user_db.update(
                        user, {"oidc_expiry": oidc_expiry}
                    )
                    user.oidc_expiry = oidc_expiry

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
            # Coalesce concurrent refreshes for the same user. Re-read the
            # account inside the lock so the second coroutine sees the
            # refreshed `expires_at` (and `refresh_token` for IdPs that
            # rotate) and skips the redundant POST.
            user_lock = await _get_user_refresh_lock(user.id)
            async with user_lock:
                try:
                    await db_session.refresh(oauth_account)
                except Exception:
                    # `db_session.refresh` can fail when oauth_account is
                    # detached from this session (e.g. pre-loaded by the
                    # caller). Fall through and attempt the refresh anyway —
                    # at worst the second coroutine sees the same stale
                    # state we'd see without the lock.
                    pass

                if (
                    oauth_account.expires_at
                    and oauth_account.expires_at - now_timestamp >= buffer_seconds
                ):
                    # Another coroutine already refreshed this account.
                    continue

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
