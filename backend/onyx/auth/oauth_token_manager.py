import math
import time
from typing import Any

import requests

from onyx.oauth.protocol import (
    OAuthFlowParams,
    build_authorization_code_token_body,
)
from onyx.server.security.models import outbound_ssrf_params
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
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
