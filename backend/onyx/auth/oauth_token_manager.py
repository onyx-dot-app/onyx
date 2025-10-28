import time
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from onyx.db.models import OAuthConfig
from onyx.db.models import OAuthUserToken
from onyx.db.oauth_config import get_user_oauth_token
from onyx.db.oauth_config import upsert_user_oauth_token
from onyx.utils.logger import setup_logger


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

        token_data = user_token.token_data

        # Check if token is expired
        if OAuthTokenManager.is_token_expired(token_data):
            # Try to refresh if we have a refresh token
            if "refresh_token" in token_data:
                try:
                    return self.refresh_token(user_token)
                except Exception as e:
                    logger.warning(f"Failed to refresh token: {e}")
                    return None
            else:
                return None

        return token_data.get("access_token")

    def refresh_token(self, user_token: OAuthUserToken) -> str:
        """Refresh access token using refresh token"""
        token_data = user_token.token_data

        response = requests.post(
            self.oauth_config.token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token_data["refresh_token"],
                "client_id": self.oauth_config.client_id,
                "client_secret": self.oauth_config.client_secret,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()

        new_token_data = response.json()

        # Calculate expires_at if expires_in is present
        if "expires_in" in new_token_data:
            new_token_data["expires_at"] = (
                int(time.time()) + new_token_data["expires_in"]
            )

        # Preserve refresh_token if not returned (some providers don't return it)
        if "refresh_token" not in new_token_data and "refresh_token" in token_data:
            new_token_data["refresh_token"] = token_data["refresh_token"]

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
        response = requests.post(
            self.oauth_config.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.oauth_config.client_id,
                "client_secret": self.oauth_config.client_secret,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()

        token_data = response.json()

        # Calculate expires_at if expires_in is present
        if "expires_in" in token_data:
            token_data["expires_at"] = int(time.time()) + token_data["expires_in"]

        return token_data

    @staticmethod
    def build_authorization_url(
        oauth_config: OAuthConfig, redirect_uri: str, state: str
    ) -> str:
        """Build OAuth authorization URL"""
        params: dict[str, Any] = {
            "client_id": oauth_config.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }

        # Add scopes if configured
        if oauth_config.scopes:
            params["scope"] = " ".join(oauth_config.scopes)

        # Add any additional provider-specific parameters
        if oauth_config.additional_params:
            params.update(oauth_config.additional_params)

        # Check if URL already has query parameters
        separator = "&" if "?" in oauth_config.authorization_url else "?"

        return f"{oauth_config.authorization_url}{separator}{urlencode(params)}"
