"""Central home for MCP credential/authentication questions.

Several distinct business questions used to share the name ``is_authenticated``.
Each function here answers exactly one, with the consumer noted:

- ``ResolvedMCPCredentials.can_authenticate`` — are the effective credentials
  usable for a call right now (lazy refresh still allowed)? Consumed by the
  tool runtime, the sandbox proxy, and the API status fields.
- ``ResolvedMCPCredentials.needs_reauth`` — is the stored OAuth grant dead
  (expired with no refresh token), so the user must reconnect?
- ``mcp_token_expired`` — is the stored OAuth access token past its expiry
  (regardless of whether a refresh token could revive it)? Drives refresh.
- ``requires_user_authentication`` — does the server's shape require a per-user
  credential at all, or is it usable from admin/none config alone?
- ``user_can_authenticate`` — resolves the user's credentials and reports
  whether they authenticate; the DB-backed entry point for status listings.

This module holds pure logic plus the resolve orchestration; the DB fetch lives
in ``onyx.db.mcp``. It must not import ``onyx.server.features.mcp.oauth``.
"""

import time
from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.db.enums import MCPAuthenticationPerformer, MCPAuthenticationType
from onyx.db.mcp import get_user_connection_config
from onyx.db.models import MCPConnectionConfig, MCPServer, User
from onyx.server.features.mcp.models import (
    DENYLISTED_MCP_HEADERS,
    MCPAuthTemplate,
    MCPConnectionData,
    MCPOAuthKeys,
    merge_mcp_headers,
)
from onyx.utils.logger import setup_logger
from onyx.utils.sensitive import SensitiveValue

logger = setup_logger()


class MCPCredentialsError(Exception):
    """Credentials for an MCP server cannot be resolved for this user."""


def extract_connection_data(
    config: MCPConnectionConfig | None, apply_mask: bool = False
) -> MCPConnectionData:
    """Extract MCPConnectionData from a connection config, with proper typing.

    This helper encapsulates the cast from the JSON column's dict[str, Any]
    to the typed MCPConnectionData structure.
    """
    if config is None or config.config is None:
        return MCPConnectionData(headers={})
    if isinstance(config.config, SensitiveValue):
        return cast(MCPConnectionData, config.config.get_value(apply_mask=apply_mask))
    return cast(MCPConnectionData, config.config)


def mcp_token_expired(config_data: MCPConnectionData) -> bool:
    """True iff the stored access token is past its persisted expiry."""
    expires_at = config_data.get(MCPOAuthKeys.TOKEN_EXPIRES_AT.value)
    return expires_at is not None and float(expires_at) <= time.time()


def requires_user_authentication(
    auth_type: MCPAuthenticationType | None,
    auth_performer: MCPAuthenticationPerformer | None,
) -> bool:
    """Whether the server's shape needs a per-user credential. False when the
    server requires no auth, or an admin supplies shared credentials for
    everyone. Consumed at server create/update to report initial auth state."""
    if auth_type == MCPAuthenticationType.NONE:
        return False
    if auth_performer == MCPAuthenticationPerformer.ADMIN:
        return False
    return True


def get_mcp_auth_template(mcp_server: MCPServer) -> MCPAuthTemplate | None:
    """Read the canonical admin template, including legacy per-user API keys."""
    config = mcp_server.admin_connection_config
    if config is None:
        return None
    data = extract_connection_data(config, apply_mask=False)
    headers = data.get("header_template")
    if headers is None and (
        mcp_server.auth_type == MCPAuthenticationType.API_TOKEN
        and mcp_server.auth_performer == MCPAuthenticationPerformer.PER_USER
    ):
        headers = data.get("headers")
    if headers is None:
        return None
    return MCPAuthTemplate(headers=headers)


class ResolvedMCPCredentials(BaseModel):
    """Effective connection state for one MCP server and user."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    connection_config: MCPConnectionConfig | None
    user_oauth_token: str | None
    auth_type: MCPAuthenticationType | None = None
    auth_template: MCPAuthTemplate | None = None
    user_email: str = ""

    def _config_data(self) -> MCPConnectionData:
        return extract_connection_data(self.connection_config, apply_mask=False)

    def _template_substitutions(self) -> dict[str, str]:
        data = self._config_data()
        substitutions = dict(data.get("header_substitutions", {}))
        if api_token := data.get("api_token"):
            substitutions["api_key"] = api_token
        return substitutions

    def _configured_headers(self) -> dict[str, str]:
        data = self._config_data()
        template_headers: dict[str, str] = {}
        if self.auth_template is not None and self._has_required_substitutions():
            template_headers = self.auth_template.render(
                self._template_substitutions(), user_email=self.user_email
            )
        return merge_mcp_headers(data.get("headers", {}), template_headers)

    def _generated_auth_headers(self) -> dict[str, str]:
        if self.user_oauth_token:
            return {"Authorization": f"Bearer {self.user_oauth_token}"}
        if self.auth_type != MCPAuthenticationType.OAUTH:
            return {}
        tokens = self._config_data().get(MCPOAuthKeys.TOKENS.value)
        if not tokens:
            return {}
        token_type = tokens.get("token_type")
        access_token = tokens.get("access_token")
        if not token_type or not access_token:
            return {}
        return {"Authorization": f"{token_type} {access_token}"}

    def _has_required_substitutions(self) -> bool:
        if self.auth_template is None or not self.auth_template.required_fields:
            return True
        substitutions = self._template_substitutions()
        return all(
            substitutions.get(field) for field in self.auth_template.required_fields
        )

    def build_headers(self) -> dict[str, str]:
        """Build configured headers with generated authentication taking precedence."""
        stored = merge_mcp_headers(
            self._configured_headers(), self._generated_auth_headers()
        )
        headers = {
            k: v for k, v in stored.items() if k.lower() not in DENYLISTED_MCP_HEADERS
        }
        if len(headers) != len(stored):
            # Names only — header values are credentials.
            logger.warning(
                "Stored MCP credential headers contained denylisted headers "
                "that were stripped: %s",
                sorted(k for k in stored if k.lower() in DENYLISTED_MCP_HEADERS),
            )
        return headers

    def needs_reauth(self) -> bool:
        """The stored OAuth grant is dead: the access token is expired and
        there is no refresh token to redeem, so only a user reconnect can
        restore it. Its bearer header still takes precedence in
        ``build_headers``, so no caller-supplied header can work around it."""
        if self.auth_type != MCPAuthenticationType.OAUTH:
            return False
        config_data = self._config_data()
        if not mcp_token_expired(config_data):
            return False
        tokens = config_data.get(MCPOAuthKeys.TOKENS.value) or {}
        return not tokens.get("refresh_token")

    def can_authenticate(self) -> bool:
        """Whether these credentials can authenticate a call now (lazy refresh
        of an expired-but-refreshable OAuth token still allowed downstream)."""
        if self.auth_type in (None, MCPAuthenticationType.NONE):
            return self._has_required_substitutions()
        if self.auth_type == MCPAuthenticationType.PT_OAUTH:
            return bool(self.user_oauth_token) and self._has_required_substitutions()
        if self.auth_type == MCPAuthenticationType.OAUTH:
            # A dead grant must read as unauthenticated so the UI prompts a
            # reconnect and Craft configs exclude the server.
            return (
                bool(self._generated_auth_headers())
                and not self.needs_reauth()
                and self._has_required_substitutions()
            )
        return bool(self._configured_headers()) and self._has_required_substitutions()


def resolve_mcp_credentials(
    mcp_server: MCPServer,
    user: User,
    db_session: Session,
    *,
    user_configs: Mapping[int, MCPConnectionConfig] | None = None,
) -> ResolvedMCPCredentials:
    """Combine the admin template, user substitutions, and generated auth.

    `user_configs` may preload every requested server's user row; a missing key
    means no stored user values.
    """
    auth_template = get_mcp_auth_template(mcp_server)
    user_connection_config = (
        user_configs.get(mcp_server.id)
        if user_configs is not None
        else get_user_connection_config(mcp_server.id, user.email, db_session)
    )

    if mcp_server.auth_type == MCPAuthenticationType.PT_OAUTH:
        if user.is_anonymous:
            raise MCPCredentialsError(
                f"Anonymous user cannot use PT_OAUTH MCP server {mcp_server.id}"
            )
        return ResolvedMCPCredentials(
            connection_config=user_connection_config,
            user_oauth_token=(
                user.oauth_accounts[0].access_token if user.oauth_accounts else None
            ),
            auth_type=mcp_server.auth_type,
            auth_template=auth_template,
            user_email=user.email,
        )

    if mcp_server.auth_type in (
        MCPAuthenticationType.API_TOKEN,
        MCPAuthenticationType.OAUTH,
    ):
        if mcp_server.auth_performer == MCPAuthenticationPerformer.PER_USER:
            connection_config = user_connection_config
        else:
            connection_config = mcp_server.admin_connection_config
        return ResolvedMCPCredentials(
            connection_config=connection_config,
            user_oauth_token=None,
            auth_type=mcp_server.auth_type,
            auth_template=auth_template,
            user_email=user.email,
        )

    return ResolvedMCPCredentials(
        connection_config=user_connection_config,
        user_oauth_token=None,
        auth_type=mcp_server.auth_type,
        auth_template=auth_template,
        user_email=user.email,
    )


def user_can_authenticate(
    mcp_server: MCPServer,
    user: User,
    db_session: Session,
    *,
    user_configs: Mapping[int, MCPConnectionConfig] | None = None,
) -> bool:
    """Resolve the user's credentials and report whether they authenticate:
    every generated credential and template value is available."""
    try:
        credentials = resolve_mcp_credentials(
            mcp_server, user, db_session, user_configs=user_configs
        )
    except MCPCredentialsError:
        return False
    return credentials.can_authenticate()
