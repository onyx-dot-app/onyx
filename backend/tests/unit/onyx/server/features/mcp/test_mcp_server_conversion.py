"""Unit tests for _db_mcp_server_to_api_mcp_server handling of empty OAuth credentials.

These tests verify that the conversion function handles empty/missing OAuth
client_id gracefully (warning + empty credentials) rather than raising ValueError.
"""

from datetime import datetime
from datetime import timezone
from unittest.mock import MagicMock
from unittest.mock import patch

from onyx.auth.schemas import UserRole
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPServerStatus
from onyx.server.features.mcp.api import _db_mcp_server_to_api_mcp_server


def _make_db_server(
    auth_type: MCPAuthenticationType,
    auth_performer: MCPAuthenticationPerformer,
    admin_config_data: dict | None = None,
) -> MagicMock:
    """Create a mock DbMCPServer with the given auth settings."""
    db_server = MagicMock()
    db_server.id = 1
    db_server.name = "Test Server"
    db_server.description = "A test server"
    db_server.server_url = "https://example.com/mcp"
    db_server.owner = "admin@example.com"
    db_server.transport = None
    db_server.auth_type = auth_type
    db_server.auth_performer = auth_performer
    db_server.status = MCPServerStatus.CONNECTED
    db_server.last_refreshed_at = datetime.now(timezone.utc)
    db_server.current_actions = []

    if admin_config_data is not None:
        config_mock = MagicMock()
        # The container code accesses .config directly as a dict
        config_mock.config = admin_config_data
        db_server.admin_connection_config = config_mock
        db_server.admin_connection_config_id = 1
    else:
        db_server.admin_connection_config = None
        db_server.admin_connection_config_id = None

    return db_server


def _make_admin_user() -> MagicMock:
    """Create a mock admin User."""
    user = MagicMock()
    user.email = "admin@example.com"
    user.role = UserRole.ADMIN
    return user


@patch("onyx.server.features.mcp.api.get_user_connection_config", return_value=None)
class TestMCPServerConversionEmptyOAuth:
    """Tests that empty OAuth client_id doesn't crash the conversion function."""

    def test_admin_performer_empty_client_id_returns_empty_credentials(
        self,
        _mock_user_config: MagicMock,
    ) -> None:
        """When admin-performer OAuth server has empty client_id,
        conversion should succeed with empty admin_credentials."""
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            admin_config_data={
                "client_info": {
                    "client_id": "",
                    "client_secret": "some-secret",
                    "redirect_uris": ["https://example.com/callback"],
                },
            },
        )
        user = _make_admin_user()
        db = MagicMock()

        result = _db_mcp_server_to_api_mcp_server(
            db_server, db, user, include_auth_config=True
        )

        assert result.admin_credentials == {}

    def test_admin_performer_null_client_secret_still_works(
        self,
        _mock_user_config: MagicMock,
    ) -> None:
        """When admin-performer OAuth server has valid client_id but null client_secret,
        conversion should succeed with only client_id in admin_credentials."""
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            admin_config_data={
                "client_info": {
                    "client_id": "valid-client-id",
                    "client_secret": None,
                    "redirect_uris": ["https://example.com/callback"],
                },
            },
        )
        user = _make_admin_user()
        db = MagicMock()

        result = _db_mcp_server_to_api_mcp_server(
            db_server, db, user, include_auth_config=True
        )

        assert result.admin_credentials is not None
        assert "client_id" in result.admin_credentials
        assert "client_secret" not in result.admin_credentials

    def test_per_user_performer_empty_client_id_returns_empty_credentials(
        self,
        _mock_user_config: MagicMock,
    ) -> None:
        """When per-user-performer OAuth server has empty client_id,
        conversion should succeed with empty admin_credentials."""
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            admin_config_data={
                "client_info": {
                    "client_id": "",
                    "client_secret": "some-secret",
                    "redirect_uris": ["https://example.com/callback"],
                },
            },
        )
        user = _make_admin_user()
        db = MagicMock()

        result = _db_mcp_server_to_api_mcp_server(
            db_server, db, user, include_auth_config=True
        )

        assert result.admin_credentials == {}

    def test_per_user_performer_null_client_secret_still_works(
        self,
        _mock_user_config: MagicMock,
    ) -> None:
        """When per-user-performer OAuth server has valid client_id but null client_secret,
        conversion should succeed with only client_id in admin_credentials."""
        db_server = _make_db_server(
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            admin_config_data={
                "client_info": {
                    "client_id": "valid-client-id",
                    "client_secret": None,
                    "redirect_uris": ["https://example.com/callback"],
                },
            },
        )
        user = _make_admin_user()
        db = MagicMock()

        result = _db_mcp_server_to_api_mcp_server(
            db_server, db, user, include_auth_config=True
        )

        assert result.admin_credentials is not None
        assert "client_id" in result.admin_credentials
        assert "client_secret" not in result.admin_credentials
