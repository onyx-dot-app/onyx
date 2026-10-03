"""Admin-defined OAuth 2.0 for CUSTOM external apps: the validated flow config
stored on ``external_app.oauth_config`` and the config-driven
:class:`OAuthFlowHandler` built from it.

The config holds no secrets. The OAuth client credentials live in the app's
encrypted ``organization_credentials`` under the same ``client_id`` /
``client_secret`` keys built-in providers use, so the OAuth routes, the lazy
refresh path, and the admin credential-masking logic need no CUSTOM special
case.
"""

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, field_validator

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import (
    OAuthFlowHandler,
    OAuthFlowSpec,
    TokenEndpointAuthMethod,
)

# The organization-credential keys an OAuth-enabled custom app must carry.
OAUTH_CLIENT_ID_KEY = "client_id"
OAUTH_CLIENT_SECRET_KEY = "client_secret"

# The per-user credential key the OAuth flow fills in. A custom OAuth app's
# ``auth_template`` must reference it (and nothing else the flow can't supply).
ACCESS_TOKEN_PLACEHOLDER = "access_token"

# Protocol params the flow itself sets (code grant + CSRF state); admin extras
# may not override them.
_RESERVED_AUTHORIZE_PARAMS = frozenset(
    {"response_type", "client_id", "redirect_uri", "state", "scope"}
)


class CustomOAuthConfig(BaseModel):
    """Authorization-code-flow parameters for an admin-defined OAuth app,
    stored as ``external_app.oauth_config``. No secrets — client creds live in
    ``organization_credentials``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorize_url: str
    token_url: str
    # Requested scopes. Empty means "don't send a scope param" (provider
    # defaults).
    scopes: list[str] = []
    # The query param the joined scopes ride under (Slack: `user_scope`).
    scope_param: str = "scope"
    # Space by default (RFC 6749 §3.3); a few providers want commas.
    scope_delimiter: str = " "
    # E.g. `access_type=offline` / `prompt=consent` for Google-style refresh
    # tokens. May not name a reserved protocol param.
    extra_authorize_params: dict[str, str] = {}
    token_endpoint_auth_method: TokenEndpointAuthMethod = (
        TokenEndpointAuthMethod.CLIENT_SECRET_POST
    )

    @field_validator("authorize_url", "token_url")
    @classmethod
    def _absolute_https_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("must be an absolute https:// URL")
        # The api server POSTs to token_url; refuse credential-bearing URLs.
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("must not contain userinfo (user:pass@)")
        if parsed.fragment:
            raise ValueError("must not contain a fragment")
        return value

    @field_validator("scopes")
    @classmethod
    def _clean_scopes(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for scope in value:
            scope = scope.strip()
            if not scope:
                continue
            if any(ch.isspace() for ch in scope):
                raise ValueError(f"scope '{scope}' must not contain whitespace")
            if scope not in cleaned:
                cleaned.append(scope)
        return cleaned

    @field_validator("scope_param")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("scope_delimiter")
    @classmethod
    def _delimiter(cls, value: str) -> str:
        if value not in (" ", ","):
            raise ValueError("must be a single space or a comma")
        return value

    @field_validator("extra_authorize_params")
    @classmethod
    def _no_reserved_params(cls, value: dict[str, str]) -> dict[str, str]:
        reserved = sorted(_RESERVED_AUTHORIZE_PARAMS & value.keys())
        if reserved:
            raise ValueError(
                f"may not override protocol parameters: {', '.join(reserved)}"
            )
        for key in value:
            if not key.strip():
                raise ValueError("parameter names must be non-empty")
        return value

    @property
    def scope(self) -> str:
        return self.scope_delimiter.join(self.scopes)


class CustomOAuthHandler(OAuthFlowHandler):
    """Config-driven :class:`OAuthFlowHandler` for a CUSTOM app. Credential
    extraction is plain RFC 6749: ``access_token`` required, optional fields
    kept when present."""

    def __init__(self, config: CustomOAuthConfig) -> None:
        self.config = config
        self.token_endpoint_auth_method = config.token_endpoint_auth_method
        self._oauth = OAuthFlowSpec(
            authorize_url=config.authorize_url,
            token_url=config.token_url,
            scope=config.scope,
            scope_param=config.scope_param,
            extra_authorize_params={
                "response_type": "code",
                # Collision-free: the validator rejects reserved params.
                **config.extra_authorize_params,
            },
        )

    @property
    def oauth(self) -> OAuthFlowSpec:
        return self._oauth

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token or not isinstance(access_token, str):
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "OAuth token response did not contain an access token.",
            )
        creds: dict[str, Any] = {"access_token": access_token}
        if response_data.get("token_type") is not None:
            creds["token_type"] = response_data["token_type"]
        if response_data.get("scope") is not None:
            creds["scope"] = response_data["scope"]
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        # Presence, not truthiness: `expires_in: 0` means already expired, and
        # dropping it would read downstream as never-expiring.
        if response_data.get("expires_in") is not None:
            creds["expires_in"] = response_data["expires_in"]
        return creds


def validate_custom_oauth_app(
    organization_credentials: dict[str, Any],
    *,
    placeholders: set[str],
) -> None:
    """Invariants for a CUSTOM app that carries an ``oauth_config``:

    * ``organization_credentials`` must hold the OAuth ``client_id`` and
      ``client_secret`` (the keys the OAuth routes read).
    * ``auth_template`` must reference ``{access_token}`` — otherwise the
      token the user grants is never injected.
    * ``access_token`` may not be an org credential (the app would read as
      "connected" for everyone without any OAuth grant).
    * No other placeholder may be left for the user to fill: the OAuth flow
      is the only per-user input, so anything else must be org-pre-filled.

    ``placeholders`` is the set of ``{name}`` references in the app's
    ``auth_template`` (computed by the caller with the shared template grammar).
    """
    for key in (OAUTH_CLIENT_ID_KEY, OAUTH_CLIENT_SECRET_KEY):
        if not str(organization_credentials.get(key) or "").strip():
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"An OAuth app requires the organization credential '{key}'.",
            )
    if ACCESS_TOKEN_PLACEHOLDER not in placeholders:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "An OAuth app's auth_template must reference {access_token} "
            '(e.g. {"Authorization": "Bearer {access_token}"}).',
        )
    if ACCESS_TOKEN_PLACEHOLDER in organization_credentials:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "access_token is supplied per user by the OAuth flow and cannot be "
            "an organization credential.",
        )
    unfillable = sorted(
        placeholders - set(organization_credentials) - {ACCESS_TOKEN_PLACEHOLDER}
    )
    if unfillable:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "auth_template references credentials the OAuth flow cannot supply: "
            f"{', '.join(unfillable)}. Use {{access_token}} or pre-fill them as "
            "organization credentials.",
        )
