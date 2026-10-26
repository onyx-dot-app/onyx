"""Pure request construction for outgoing OAuth authorization-code flows."""

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import BaseModel

OAUTH_RESPONSE_TYPE_CODE = "code"
OAUTH_GRANT_TYPE_AUTHORIZATION_CODE = "authorization_code"
OAUTH_PKCE_CHALLENGE_METHOD_S256 = "S256"

# Providers that issue a refresh token only when the authorization request
# explicitly asks for offline access, keyed by authorization-endpoint host.
# Without these params the grant dies at access-token expiry with no way to
# refresh. Explicitly configured params always win over these defaults.
_OFFLINE_ACCESS_AUTH_PARAMS_BY_HOST: dict[str, dict[str, str]] = {
    # `prompt=consent` because Google issues a refresh token only on flows
    # that show the consent screen; a silent re-auth would leave a reconnected
    # config without one. Matches Onyx's own Google login flow.
    "accounts.google.com": {"access_type": "offline", "prompt": "consent"},
}

_PROTOCOL_AUTHORIZATION_PARAMS = frozenset(
    {
        "client_id",
        "code_challenge",
        "code_challenge_method",
        "redirect_uri",
        "response_type",
        "scope",
        "state",
    }
)


def ensure_offline_access_auth_params(authorization_url: str) -> str:
    """Merge missing offline-access params into a built authorize URL.
    Params already in the URL win."""
    parsed = urlparse(authorization_url)
    defaults = _OFFLINE_ACCESS_AUTH_PARAMS_BY_HOST.get((parsed.hostname or "").lower())
    if not defaults:
        return authorization_url
    query = parse_qsl(parsed.query, keep_blank_values=True)
    configured_keys = {key for key, _ in query}
    missing = {
        key: value for key, value in defaults.items() if key not in configured_keys
    }
    if not missing:
        return authorization_url
    query.extend(missing.items())
    return urlunparse(parsed._replace(query=urlencode(query)))


class OAuthFlowParams(BaseModel):
    """Stateless inputs for the OAuth 2.0 authorization-code grant, decoupled
    from any storage model so both `OAuthConfig`-backed tool OAuth and MCP
    known-provider OAuth can share the wire primitives below."""

    authorization_url: str
    token_url: str
    client_id: str
    client_secret: str | None = None
    scopes: list[str] | None = None
    additional_params: dict[str, Any] | None = None


def validate_authorization_params(
    authorization_url: str,
    additional_params: Mapping[str, object] | None,
    *,
    owns_resource: bool = False,
    scope_param: str = "scope",
) -> None:
    """Reject flow-owned parameters in endpoint queries and configured extras."""
    if (
        scope_param in _PROTOCOL_AUTHORIZATION_PARAMS - {"scope"}
        or scope_param == "resource"
    ):
        raise ValueError("OAuth scope parameter conflicts with a protocol field")
    configured: dict[str, object] = dict(
        parse_qsl(urlparse(authorization_url).query, keep_blank_values=True)
    )
    configured.update(additional_params or {})
    protected = _PROTOCOL_AUTHORIZATION_PARAMS | {scope_param}
    if owns_resource:
        protected = protected | {"resource"}
    conflicts = protected.intersection(configured)
    if conflicts:
        raise ValueError(
            "OAuth authorization parameters cannot override: "
            + ", ".join(sorted(conflicts))
        )


def build_authorization_url(
    *,
    authorization_url: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    scope: str | None = None,
    scope_param: str = "scope",
    additional_params: Mapping[str, object] | None = None,
    code_challenge: str | None = None,
    resource: str | None = None,
    owns_resource: bool = False,
) -> str:
    """Merge provider parameters without allowing overrides of protocol fields."""
    validate_authorization_params(
        authorization_url,
        additional_params,
        owns_resource=owns_resource or resource is not None,
        scope_param=scope_param,
    )
    parsed = urlparse(authorization_url)
    query: dict[str, object] = dict(additional_params or {})
    query.update(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": OAUTH_RESPONSE_TYPE_CODE,
            "state": state,
        }
    )
    if scope is not None:
        query[scope_param] = scope
    if code_challenge is not None:
        query["code_challenge"] = code_challenge
        query["code_challenge_method"] = OAUTH_PKCE_CHALLENGE_METHOD_S256
    if resource is not None:
        query["resource"] = resource
    existing = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in query
    ]
    return ensure_offline_access_auth_params(
        urlunparse(parsed._replace(query=urlencode([*existing, *query.items()])))
    )


def build_authorization_code_token_body(
    *,
    code: str,
    redirect_uri: str,
    client_id: str | None = None,
    client_secret: str | None = None,
    code_verifier: str | None = None,
) -> dict[str, str]:
    """Build grant fields; omit client credentials supplied through HTTP Basic."""
    body = {
        "grant_type": OAUTH_GRANT_TYPE_AUTHORIZATION_CODE,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if client_id is not None:
        body["client_id"] = client_id
    if client_secret is not None:
        body["client_secret"] = client_secret
    if code_verifier is not None:
        body["code_verifier"] = code_verifier
    return body
