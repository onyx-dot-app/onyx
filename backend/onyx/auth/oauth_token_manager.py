import math
import time
from typing import Any
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from onyx.db.models import OAuthConfig, OAuthUserToken, User
from onyx.db.oauth_config import (
    get_oauth_config,
    get_user_oauth_token,
    update_user_oauth_token_if_unchanged,
)
from onyx.oauth.protocol import (
    OAuthFlowParams,
    build_authorization_code_token_body,
)
from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.sensitive import SensitiveValue
from onyx.utils.url import validate_outbound_http_url


def validate_oauth_endpoint_url(url: str, *, resolve_dns: bool = True) -> None:
    """SSRF guard for admin-configured OAuth endpoints, shared by store-time
    (MCP upsert) and fetch-time (token exchange/refresh) so the policy can't
    drift. Validation is driven by the admin ``SSRF Protection`` setting: at the
    VALIDATE_* levels private/internal targets are blocked; when DISABLED,
    private + loopback become reachable while cloud-metadata stays blocked.
    ``https_only`` since OAuth endpoints must be TLS. ``resolve_dns=False`` skips
    the DNS lookup at store time; fetch time still resolves."""
    params = outbound_ssrf_params(get_security_settings().ssrf_protection_level)
    validate_outbound_http_url(
        url,
        allow_private_network=params.allow_private_network,
        https_only=True,
        block_loopback_and_link_local=params.block_loopback_and_link_local,
        block_link_local_only=params.block_link_local_only,
        resolve_dns=resolve_dns,
    )


logger = setup_logger()


def exchange_oauth_code_for_token(
    params: OAuthFlowParams,
    code: str,
    redirect_uri: str,
    *,
    code_verifier: str | None = None,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens at the token endpoint. Sends
    `code_verifier` when provided (PKCE). Returns the raw provider payload with
    a computed `expires_at`; raises `requests.HTTPError` on a non-2xx response."""
    data = build_authorization_code_token_body(
        code=code,
        redirect_uri=redirect_uri,
        client_id=params.client_id,
        client_secret=params.client_secret or None,
        code_verifier=code_verifier,
    )

    return _post_oauth_token_request(params.token_url, data)


def _post_oauth_token_request(token_url: str, data: dict[str, str]) -> dict[str, Any]:
    """Validate the endpoint and token response before callers persist tokens."""
    validate_oauth_endpoint_url(token_url)
    response = requests.post(
        token_url,
        data=data,
        headers={"Accept": "application/json"},
        timeout=30,
        allow_redirects=False,
    )
    response.raise_for_status()
    if 300 <= response.status_code < 400:
        raise ValueError("OAuth token endpoint must not redirect")

    token_data = response.json()
    if (
        not isinstance(token_data, dict)
        or not isinstance(token_data.get("access_token"), str)
        or not token_data["access_token"]
    ):
        raise ValueError("OAuth token response must contain a non-empty access token")
    if "expires_in" in token_data:
        expires_in = token_data["expires_in"]
        try:
            valid_expiration = (
                not isinstance(expires_in, bool)
                and isinstance(expires_in, (int, float))
                and math.isfinite(expires_in)
                and expires_in >= 0
            )
        except OverflowError:
            valid_expiration = False
        if not valid_expiration:
            raise ValueError("OAuth token response has an invalid expiration")
        token_data["expires_at"] = int(time.time()) + expires_in
    return token_data


def get_tool_access_token(
    *,
    oauth_config_id: int | None,
    passthrough_auth: bool,
    user: User | None,
    db_session: Session,
) -> str | None:
    """Resolve custom-action authentication for both chat and Craft."""
    if user is None or user.is_anonymous:
        return None
    if oauth_config_id is not None:
        config = get_oauth_config(oauth_config_id, db_session)
        if config is None:
            return None
        return OAuthTokenManager(config, user.id, db_session).get_valid_access_token()
    return user.live_oauth_token if passthrough_auth else None


class OAuthTokenManager:
    """Manages OAuth token retrieval, refresh, and validation"""

    def __init__(self, oauth_config: OAuthConfig, user_id: UUID, db_session: Session):
        self.oauth_config = oauth_config
        self.user_id = user_id
        self.db_session = db_session

    def has_usable_access_token(self) -> bool:
        """Check stored credentials without refreshing or contacting the provider."""
        user_token = get_user_oauth_token(
            self.oauth_config.id, self.user_id, self.db_session
        )
        if user_token is None or not user_token.token_data:
            return False
        token_data = self._unwrap_token_data(user_token.token_data)
        return bool(token_data.get("access_token")) and (
            not self.is_token_expired(token_data)
            or bool(token_data.get("refresh_token"))
        )

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

        data: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
            "client_id": _unwrap_sensitive_str(self.oauth_config.client_id),
            "client_secret": _unwrap_sensitive_str(self.oauth_config.client_secret),
        }
        new_token_data = _post_oauth_token_request(self.oauth_config.token_url, data)

        # Preserve refresh_token if not returned (some providers don't return it)
        if "refresh_token" not in new_token_data and "refresh_token" in token_data:
            new_token_data["refresh_token"] = token_data["refresh_token"]

        if not update_user_oauth_token_if_unchanged(
            user_token.id, token_data, new_token_data, self.db_session
        ):
            raise ValueError("OAuth connection changed during token refresh")

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

    @staticmethod
    def _unwrap_token_data(
        token_data: SensitiveValue[dict[str, Any]] | dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(token_data, SensitiveValue):
            return token_data.get_value(  # ty: ignore[invalid-return-type]
                apply_mask=False
            )
        return token_data


def _unwrap_sensitive_str(value: SensitiveValue[str] | str) -> str:
    if isinstance(value, SensitiveValue):
        return value.get_value(apply_mask=False)  # ty: ignore[invalid-return-type]
    return value


def oauth_flow_params_from_config(
    oauth_config: OAuthConfig, *, allow_missing_credentials: bool = False
) -> OAuthFlowParams:
    """Read protocol inputs without loading or changing a user's tokens."""
    if not allow_missing_credentials and (
        oauth_config.client_id is None or oauth_config.client_secret is None
    ):
        raise ValueError("OAuth client_id and client_secret are required")
    client_id = (
        _unwrap_sensitive_str(oauth_config.client_id)
        if oauth_config.client_id is not None
        else ""
    )
    client_secret = (
        _unwrap_sensitive_str(oauth_config.client_secret)
        if oauth_config.client_secret is not None
        else None
    )
    if not client_id and not allow_missing_credentials:
        raise ValueError("OAuth client_id is required")
    return OAuthFlowParams(
        authorization_url=oauth_config.authorization_url,
        token_url=oauth_config.token_url,
        client_id=client_id,
        client_secret=client_secret,
        scopes=oauth_config.scopes,
        additional_params=oauth_config.additional_params,
    )
