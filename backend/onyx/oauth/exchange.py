"""The OAuth 2.0 authorization-code-grant wire layer, decoupled from storage.

A single set of primitives — build the authorize URL, exchange a code, exchange a
refresh token — shared by every OAuth consumer so the on-the-wire behavior (SSRF
guard, expiry computation, terminal-vs-transient classification, refresh-token
preservation) can't drift between tool OAuth, MCP, and Craft external apps.
"""

import time
from typing import Any
from urllib.parse import urlencode

import requests
from pydantic import BaseModel

from onyx.oauth.errors import token_response_error
from onyx.oauth.errors import TokenRefreshTerminalError
from onyx.oauth.errors import TokenRefreshTransientError
from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException
from onyx.utils.url import validate_outbound_http_url

logger = setup_logger()

OAUTH_RESPONSE_TYPE_CODE = "code"
OAUTH_GRANT_TYPE_AUTHORIZATION_CODE = "authorization_code"
OAUTH_PKCE_CHALLENGE_METHOD_S256 = "S256"


class OAuthFlowParams(BaseModel):
    """Stateless inputs for the OAuth 2.0 authorization-code grant, decoupled
    from any storage model so `OAuthConfig`-backed tool OAuth and MCP
    known-provider OAuth can share the wire primitives below."""

    authorization_url: str
    token_url: str
    client_id: str
    client_secret: str | None = None
    scopes: list[str] | None = None
    additional_params: dict[str, Any] | None = None


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


def build_oauth_authorization_url(
    params: OAuthFlowParams,
    redirect_uri: str,
    state: str,
    *,
    code_challenge: str | None = None,
    resource: str | None = None,
) -> str:
    """Construct an authorization-code-grant authorize URL. `code_challenge`
    adds PKCE (S256); `resource` adds the RFC 8707 resource indicator. Both are
    off by default so non-PKCE callers get an unchanged URL."""
    query: dict[str, Any] = {
        "client_id": params.client_id,
        "redirect_uri": redirect_uri,
        "response_type": OAUTH_RESPONSE_TYPE_CODE,
        "state": state,
    }
    if params.scopes:
        query["scope"] = " ".join(params.scopes)
    if code_challenge:
        query["code_challenge"] = code_challenge
        query["code_challenge_method"] = OAUTH_PKCE_CHALLENGE_METHOD_S256
    if resource:
        query["resource"] = resource
    if params.additional_params:
        query.update(params.additional_params)

    separator = "&" if "?" in params.authorization_url else "?"
    return f"{params.authorization_url}{separator}{urlencode(query)}"


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
    data: dict[str, str] = {
        "grant_type": OAUTH_GRANT_TYPE_AUTHORIZATION_CODE,
        "code": code,
        "client_id": params.client_id,
        "redirect_uri": redirect_uri,
    }
    if params.client_secret:
        data["client_secret"] = params.client_secret
    if code_verifier:
        data["code_verifier"] = code_verifier

    validate_oauth_endpoint_url(params.token_url)
    response = requests.post(
        params.token_url, data=data, headers={"Accept": "application/json"}
    )
    response.raise_for_status()

    token_data = response.json()
    if "expires_in" in token_data:
        token_data["expires_at"] = int(time.time()) + token_data["expires_in"]
    return token_data


# RFC 6749 §5.2: a dead grant means reconnect is required; any other failure is
# retryable. Reuses the external_apps refresh classification so all OAuth refreshers
# (tool, external-app, MCP) agree on terminal-vs-transient.
_TERMINAL_REFRESH_ERRORS = frozenset({"invalid_grant"})


def exchange_refresh_token(
    params: OAuthFlowParams,
    refresh_token: str,
) -> dict[str, Any]:
    """Exchange a refresh token for a fresh access token, computing `expires_at` and
    carrying the incoming `refresh_token` forward when the provider doesn't rotate it.

    Raises `TokenRefreshTerminalError` on a dead grant (reconnect required) and
    `TokenRefreshTransientError` on a retryable failure (network / 5xx / non-JSON)."""
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": params.client_id,
    }
    if params.client_secret:
        data["client_secret"] = params.client_secret

    try:
        validate_oauth_endpoint_url(params.token_url)
        response = requests.post(
            params.token_url, data=data, headers={"Accept": "application/json"}
        )
    except (requests.RequestException, SSRFException, ValueError) as exc:
        raise TokenRefreshTransientError(f"refresh request failed: {exc}") from exc

    try:
        token_data = response.json()
    except ValueError as exc:
        raise TokenRefreshTransientError(
            f"non-JSON token response (status={response.status_code})"
        ) from exc

    error = token_response_error(response, token_data)
    if error is not None:
        if error in _TERMINAL_REFRESH_ERRORS:
            raise TokenRefreshTerminalError(error)
        raise TokenRefreshTransientError(error)

    if "expires_in" in token_data:
        token_data["expires_at"] = int(time.time()) + token_data["expires_in"]
    if "refresh_token" not in token_data:
        token_data["refresh_token"] = refresh_token
    return token_data
