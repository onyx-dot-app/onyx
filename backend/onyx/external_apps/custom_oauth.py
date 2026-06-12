"""Admin-defined OAuth 2.0 for CUSTOM external apps: the validated flow config
stored on ``external_app.oauth_config`` and the config-driven
:class:`OAuthFlowHandler` built from it."""

from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_validator

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.oauth_handler import OAuthFlowHandler
from onyx.external_apps.oauth_handler import OAuthFlowSpec
from onyx.external_apps.oauth_handler import TokenEndpointAuthMethod

# Protocol params the flow itself sets (code grant + CSRF state); admin
# extras may not override them.
_RESERVED_AUTHORIZE_PARAMS = frozenset(
    {"response_type", "client_id", "redirect_uri", "state"}
)


class CustomOAuthConfig(BaseModel):
    """Authorization-code-flow parameters for an admin-defined OAuth app,
    stored as ``external_app.oauth_config``. No secrets — client creds live
    in ``organization_credentials``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorize_url: str
    token_url: str
    # Empty means "don't send a scope param" (provider-default scopes).
    scope: str = ""
    scope_param: str = "scope"
    # E.g. access_type=offline. May not name a reserved protocol param.
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
        # The api server POSTs to token_url; refuse credential-bearing or
        # ambiguity-prone URL forms outright.
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("must not contain userinfo (user:pass@)")
        return value

    @field_validator("scope_param")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("extra_authorize_params")
    @classmethod
    def _no_reserved_params(cls, value: dict[str, str]) -> dict[str, str]:
        reserved = sorted(_RESERVED_AUTHORIZE_PARAMS & value.keys())
        if reserved:
            raise ValueError(
                f"may not override protocol parameters: {', '.join(reserved)}"
            )
        return value


class CustomOAuthHandler(OAuthFlowHandler):
    """Config-driven handler for a CUSTOM app. Credential extraction is plain
    RFC 6749: ``access_token`` required, optional fields kept when present."""

    def __init__(self, config: CustomOAuthConfig) -> None:
        self.token_endpoint_auth_method = config.token_endpoint_auth_method
        self._oauth = OAuthFlowSpec(
            authorize_url=config.authorize_url,
            token_url=config.token_url,
            scope=config.scope,
            scope_param=config.scope_param,
            # Collision-free: the validator rejects reserved params.
            extra_authorize_params={
                "response_type": "code",
                **config.extra_authorize_params,
            },
        )

    @property
    def oauth(self) -> OAuthFlowSpec:
        return self._oauth

    def extract_credentials(self, response_data: dict[str, Any]) -> dict[str, Any]:
        access_token = response_data.get("access_token")
        if not access_token:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "OAuth token response did not contain an access token.",
            )
        creds: dict[str, Any] = {
            "access_token": access_token,
            "scope": response_data.get("scope"),
            "token_type": response_data.get("token_type"),
        }
        if response_data.get("refresh_token"):
            creds["refresh_token"] = response_data["refresh_token"]
        # Presence, not truthiness: `expires_in: 0` means already-expired,
        # and dropping it would read downstream as never-expiring.
        if response_data.get("expires_in") is not None:
            creds["expires_in"] = response_data["expires_in"]
        return creds
