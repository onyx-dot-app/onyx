import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.db.models import OAuthConfig
from onyx.db.models import OAuthUserToken
from onyx.db.oauth_config import get_user_oauth_token
from onyx.db.oauth_config import upsert_user_oauth_token
from onyx.oauth.exchange import build_oauth_authorization_url
from onyx.oauth.exchange import exchange_oauth_code_for_token
from onyx.oauth.exchange import exchange_refresh_token
from onyx.oauth.exchange import OAuthFlowParams
from onyx.utils.logger import setup_logger
from onyx.utils.sensitive import SensitiveValue

logger = setup_logger()


class OAuthTokenManager:
    """Manages OAuth token retrieval, refresh, and validation"""

    def __init__(self, oauth_config: OAuthConfig, user_id: UUID, db_session: Session):
        self.oauth_config = oauth_config
        self.user_id = user_id
        self.db_session = db_session

    def get_valid_access_token(self) -> str | None:
        """Get valid access token, refreshing if necessary"""
        user_token = get_user_oauth_token(
            self.oauth_config.id, self.user_id, self.db_session
        )

        if not user_token:
            return None

        if not user_token.token_data:
            return None

        token_data = self._unwrap_token_data(user_token.token_data)

        # Check if token is expired
        if OAuthTokenManager.is_token_expired(token_data):
            # Try to refresh if we have a refresh token
            if "refresh_token" in token_data:
                try:
                    return self.refresh_token(user_token)
                except Exception as e:
                    logger.warning("Failed to refresh token: %s", e)
                    return None
            else:
                return None

        return token_data.get("access_token")

    def refresh_token(self, user_token: OAuthUserToken) -> str:
        """Refresh access token using refresh token"""
        if not user_token.token_data:
            raise ValueError("No token data available for refresh")

        if (
            self.oauth_config.client_id is None
            or self.oauth_config.client_secret is None
        ):
            raise ValueError(
                "OAuth client_id and client_secret are required for token refresh"
            )

        token_data = self._unwrap_token_data(user_token.token_data)

        new_token_data = exchange_refresh_token(
            self._flow_params(self.oauth_config), token_data["refresh_token"]
        )

        # Update token in DB
        upsert_user_oauth_token(
            self.oauth_config.id,
            self.user_id,
            new_token_data,
            self.db_session,
        )

        return new_token_data["access_token"]

    @classmethod
    def token_expiration_time(cls, token_data: dict[str, Any]) -> int | None:
        """Get the token expiration time"""
        expires_at = token_data.get("expires_at")
        if not expires_at:
            return None

        return expires_at

    @classmethod
    def is_token_expired(cls, token_data: dict[str, Any]) -> bool:
        """Check if token is expired (with 60 second buffer)"""
        expires_at = cls.token_expiration_time(token_data)
        if not expires_at:
            return False  # No expiration data, assume valid

        # Add 60 second buffer to avoid race conditions
        return int(time.time()) + 60 >= expires_at

    def exchange_code_for_token(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange authorization code for access token"""
        if (
            self.oauth_config.client_id is None
            or self.oauth_config.client_secret is None
        ):
            raise ValueError(
                "OAuth client_id and client_secret are required for code exchange"
            )

        return exchange_oauth_code_for_token(
            self._flow_params(self.oauth_config), code, redirect_uri
        )

    @staticmethod
    def build_authorization_url(
        oauth_config: OAuthConfig, redirect_uri: str, state: str
    ) -> str:
        """Build OAuth authorization URL"""
        if oauth_config.client_id is None:
            raise ValueError("OAuth client_id is required to build authorization URL")
        return build_oauth_authorization_url(
            OAuthTokenManager._flow_params(oauth_config), redirect_uri, state
        )

    @staticmethod
    def _flow_params(oauth_config: OAuthConfig) -> OAuthFlowParams:
        if oauth_config.client_id is None:
            raise ValueError("OAuth client_id is required")
        client_secret = (
            OAuthTokenManager._unwrap_sensitive_str(oauth_config.client_secret)
            if oauth_config.client_secret is not None
            else None
        )
        return OAuthFlowParams(
            authorization_url=oauth_config.authorization_url,
            token_url=oauth_config.token_url,
            client_id=OAuthTokenManager._unwrap_sensitive_str(oauth_config.client_id),
            client_secret=client_secret,
            scopes=oauth_config.scopes,
            additional_params=oauth_config.additional_params,
        )

    @staticmethod
    def _unwrap_sensitive_str(value: SensitiveValue[str] | str) -> str:
        if isinstance(value, SensitiveValue):
            return value.get_value(apply_mask=False)  # ty: ignore[invalid-return-type]
        return value

    @staticmethod
    def _unwrap_token_data(
        token_data: SensitiveValue[dict[str, Any]] | dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(token_data, SensitiveValue):
            return token_data.get_value(  # ty: ignore[invalid-return-type]
                apply_mask=False
            )
        return token_data
