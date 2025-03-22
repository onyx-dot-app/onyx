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
from onyx.configs.app_configs import TRACK_EXTERNAL_IDP_EXPIRY
from onyx.db.models import OAuthAccount
from onyx.db.models import User
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Standard OAuth refresh token endpoints
REFRESH_ENDPOINTS = {
    "google": "https://oauth2.googleapis.com/token",
}


# NOTE: Keeping this as a utility function for potential future debugging,
# but not using it in production code
async def _test_expire_oauth_token(
    user: User,
    oauth_account: OAuthAccount,
    db_session: AsyncSession,
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

        await user_manager.user_db.update_oauth_account(
            user, cast(Any, oauth_account), updated_data
        )

        return True
    except Exception as e:
        logger.exception(f"Error setting artificial expiration: {str(e)}")
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
            f"No refresh token available for {user.email}'s {oauth_account.oauth_name} account"
        )
        return False

    provider = oauth_account.oauth_name
    if provider not in REFRESH_ENDPOINTS:
        logger.warning(f"Refresh endpoint not configured for provider: {provider}")
        return False

    try:
        logger.info(f"Refreshing OAuth token for {user.email}'s {provider} account")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                REFRESH_ENDPOINTS[provider],
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
                    f"Failed to refresh OAuth token: Status {response.status_code}"
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
            await user_manager.user_db.update_oauth_account(
                user, cast(Any, oauth_account), updated_data
            )

            logger.info(f"Successfully refreshed OAuth token for {user.email}")
            return True

    except Exception as e:
        logger.exception(f"Error refreshing OAuth token: {str(e)}")
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
            logger.info(f"OAuth token for {user.email} is about to expire - refreshing")
            success = await refresh_oauth_token(
                user, oauth_account, db_session, user_manager
            )

            if not success:
                logger.warning(
                    "Failed to refresh OAuth token. User may need to re-authenticate."
                )


async def check_oauth_account_has_refresh_token(
    user: User,
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
