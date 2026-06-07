"""Invariants for the API model returned by the per-user MCP server
listing endpoints (`GET /api/mcp/servers`,
`GET /api/mcp/servers/persona/{id}`).

The shared admin connection config row is cross-user state — it's the
OAuth `client_info` registry used by every user of a given MCP server.
Per-user state (access tokens, resolved `Authorization` headers) lives
only on the per-user row. The `auth_template` field on the API model
exists exclusively to support per-user API_TOKEN servers, where the
admin defines a header template with placeholders (e.g.
`Bearer {API_KEY}`) and the user fills the placeholders in their own
credential modal. OAuth per-user servers use the OAuth handshake URL
and never consume an `auth_template`, so the field must remain `None`
for them regardless of caller role or the contents of the shared row.
"""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.auth.schemas import UserRole
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPOAuthProviderMode
from onyx.db.enums import MCPServerStatus
from onyx.db.enums import MCPTransport
from onyx.server.features.mcp.api import _db_mcp_server_to_api_mcp_server


def _make_connection_config(config: dict[str, Any]) -> MagicMock:
    """Stand-in for `MCPConnectionConfig`; only needs a `.config`
    attribute that `extract_connection_data` can read as a plain dict
    (i.e. not wrapped in `SensitiveValue`)."""
    cfg = MagicMock()
    cfg.config = config
    return cfg


def _make_db_server(
    *,
    auth_type: MCPAuthenticationType,
    auth_performer: MCPAuthenticationPerformer,
    admin_config: MagicMock | None,
) -> MagicMock:
    server = MagicMock()
    server.id = 1
    server.name = "test-server"
    server.description = "test"
    server.server_url = "https://example.com/mcp"
    server.owner = "owner@example.com"
    server.transport = MCPTransport.STREAMABLE_HTTP
    server.auth_type = auth_type
    server.auth_performer = auth_performer
    server.admin_connection_config = admin_config
    server.admin_connection_config_id = 42 if admin_config is not None else None
    server.status = MCPServerStatus.CONNECTED
    server.last_refreshed_at = None
    server.oauth_provider_mode = MCPOAuthProviderMode.AUTO_DISCOVERY
    server.oauth_authorization_endpoint = None
    server.oauth_token_endpoint = None
    server.oauth_scopes_override = None
    server.oauth_additional_auth_params = None
    server.current_actions = []
    return server


def _make_user(*, email: str, role: UserRole) -> MagicMock:
    user = MagicMock()
    user.email = email
    user.role = role
    return user


def _oauth_admin_config_with_runtime_headers() -> MagicMock:
    """An OAuth admin connection config whose JSONB blob carries a
    realistic mix of fields: the legitimate `client_info` registry
    plus per-user-style fields (`headers`, `tokens`) that should never
    be propagated to the listing API regardless of how they got there.
    """
    return _make_connection_config(
        {
            "headers": {
                "Authorization": "Bearer xoxp-runtime-bearer-token",
            },
            "client_info": {
                "client_id": "shared-oauth-client-id",
                "client_secret": "shared-oauth-client-secret",
                "redirect_uris": ["https://onyx.example.com/mcp/oauth/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
            },
            "tokens": {
                "access_token": "xoxp-runtime-bearer-token",
                "token_type": "Bearer",
            },
        }
    )


def _api_token_template_admin_config() -> MagicMock:
    """Per-user API_TOKEN template: `headers` contains an `{API_KEY}`
    placeholder string, not a real secret. This is the legitimate
    `auth_template` payload the user-side credential modal renders."""
    return _make_connection_config(
        {
            "headers": {
                "Authorization": "Bearer {API_KEY}",
            },
            "required_fields": ["API_KEY"],
        }
    )


class TestPerUserAuthTemplateInvariants:
    def test_basic_user_oauth_server_listing_returns_no_auth_template(self) -> None:
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            admin_config=_oauth_admin_config_with_runtime_headers(),
        )
        basic_user = _make_user(email="user@example.com", role=UserRole.BASIC)

        with patch(
            "onyx.server.features.mcp.api.get_user_connection_config",
            return_value=None,
        ):
            api_server = _db_mcp_server_to_api_mcp_server(
                db_server,
                MagicMock(),
                request_user=basic_user,
                include_auth_config=False,
            )

        assert api_server.auth_template is None
        assert api_server.admin_credentials is None
        assert api_server.user_credentials is None

    def test_admin_user_oauth_server_listing_returns_no_auth_template(self) -> None:
        """Admins on the listing endpoint share the same code path as
        basic users; the OAuth invariant must apply regardless of role.
        """
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            admin_config=_oauth_admin_config_with_runtime_headers(),
        )
        admin = _make_user(email="admin@example.com", role=UserRole.ADMIN)

        with patch(
            "onyx.server.features.mcp.api.get_user_connection_config",
            return_value=None,
        ):
            api_server = _db_mcp_server_to_api_mcp_server(
                db_server,
                MagicMock(),
                request_user=admin,
                include_auth_config=False,
            )

        assert api_server.auth_template is None

    def test_owner_admin_edit_oauth_server_returns_no_auth_template(self) -> None:
        """The admin edit endpoint sets `include_auth_config=True` so
        the owner sees masked admin credentials — but the OAuth-edit
        flow consumes those via `admin_credentials.client_id` /
        `client_secret`, not via `auth_template`. The header template
        field must still be `None` for OAuth servers, and the masked
        admin credentials must not surface any runtime header value.
        """
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            admin_config=_oauth_admin_config_with_runtime_headers(),
        )
        owner = _make_user(email="owner@example.com", role=UserRole.ADMIN)

        with patch(
            "onyx.server.features.mcp.api.get_user_connection_config",
            return_value=None,
        ):
            api_server = _db_mcp_server_to_api_mcp_server(
                db_server,
                MagicMock(),
                request_user=owner,
                include_auth_config=True,
            )

        assert api_server.auth_template is None
        assert api_server.admin_credentials is not None
        assert "Authorization" not in api_server.admin_credentials
        assert all(
            "xoxp-runtime-bearer-token" not in v
            for v in api_server.admin_credentials.values()
        )

    def test_api_token_per_user_server_returns_placeholder_template(self) -> None:
        """The legitimate `auth_template` use case: per-user API_TOKEN
        servers must keep returning the placeholder header template so
        the user-side credential modal knows which fields to prompt for.
        """
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.API_TOKEN,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            admin_config=_api_token_template_admin_config(),
        )
        user = _make_user(email="user@example.com", role=UserRole.BASIC)

        with patch(
            "onyx.server.features.mcp.api.get_user_connection_config",
            return_value=None,
        ):
            api_server = _db_mcp_server_to_api_mcp_server(
                db_server,
                MagicMock(),
                request_user=user,
                include_auth_config=False,
            )

        assert api_server.auth_template is not None
        assert api_server.auth_template.headers == {
            "Authorization": "Bearer {API_KEY}",
        }
        assert api_server.auth_template.required_fields == ["API_KEY"]
