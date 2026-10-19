from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db import mcp as mcp_db
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPServerStatus,
    MCPTransport,
    Permission,
)
from onyx.db.models import MCPConnectionConfig, MCPServer, User
from onyx.server.features.mcp import api
from onyx.server.features.mcp.models import (
    MCPConnectionStatus,
    MCPServerSimpleUpdateRequest,
)


@pytest.mark.parametrize(
    "auth_type,performer",
    [
        (MCPAuthenticationType.OAUTH, MCPAuthenticationPerformer.PER_USER),
        (MCPAuthenticationType.API_TOKEN, MCPAuthenticationPerformer.ADMIN),
        (MCPAuthenticationType.API_TOKEN, MCPAuthenticationPerformer.PER_USER),
        (MCPAuthenticationType.NONE, MCPAuthenticationPerformer.PER_USER),
    ],
)
@pytest.mark.parametrize("change_url", [False, True])
def test_details_url_change_invalidates_credentials_before_returning_fresh_settings(
    monkeypatch: pytest.MonkeyPatch,
    auth_type: MCPAuthenticationType,
    performer: MCPAuthenticationPerformer,
    change_url: bool,
) -> None:
    config = MCPConnectionConfig(
        id=81, config={"headers": {"Authorization": "Bearer old-secret"}}
    )
    server = MCPServer(
        id=42,
        name="MCP",
        description="Tools",
        server_url="https://old.example/mcp",
        owner="owner@example.com",
        auth_type=auth_type,
        auth_performer=performer,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_cimd_enabled=True,
        transport=MCPTransport.STREAMABLE_HTTP,
        status=MCPServerStatus.CONNECTED,
        is_public=True,
        available_in_craft=True,
        admin_connection_config=config,
        admin_connection_config_id=config.id,
    )
    user = cast(User, SimpleNamespace(id=uuid4(), email=server.owner))
    db = MagicMock(spec=Session)
    old_user, current_user = uuid4(), uuid4()
    affected = MagicMock(
        side_effect=[{old_user}, {current_user}] if change_url else [{current_user}]
    )
    delete_users = MagicMock()
    reload_sessions = MagicMock()
    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_: server)
    monkeypatch.setattr(mcp_db, "get_mcp_server_by_id", lambda *_: server)
    monkeypatch.setattr(mcp_db, "get_connection_config_by_id", lambda *_: config)
    monkeypatch.setattr(api, "_validate_mcp_server_url", lambda *_, **__: None)
    monkeypatch.setattr(api, "can_manage_mcp_server", lambda *_: True)
    monkeypatch.setattr(
        api,
        "get_effective_permissions",
        lambda *_: {Permission.FULL_ADMIN_PANEL_ACCESS},
    )
    monkeypatch.setattr(api, "affected_user_ids_for_mcp_server", affected)
    monkeypatch.setattr(
        api, "delete_all_user_connection_configs_for_server_no_commit", delete_users
    )
    monkeypatch.setattr(api, "_hot_reload_craft_sessions", reload_sessions)
    monkeypatch.setattr(api, "get_user_connection_config", lambda *_: None)
    monkeypatch.setattr(api, "get_workspace_action_policies", lambda *_: {})
    monkeypatch.setattr(api, "users_can_manage_policies", lambda *_: True)
    result = api.update_mcp_server_simple(
        server.id,
        MCPServerSimpleUpdateRequest(
            name="Updated MCP",
            server_url="https://new.example/mcp" if change_url else server.server_url,
        ),
        db,
        user,
    )
    assert result.name == "Updated MCP"
    assert result.tool_count == 0
    if change_url:
        delete_users.assert_called_once_with(server.id, db)
        db.delete.assert_called_once_with(config)
        assert server.admin_connection_config_id is None
        assert server.admin_connection_config is None
        assert result.status == (
            MCPServerStatus.CREATED
            if auth_type == MCPAuthenticationType.NONE
            else MCPServerStatus.AWAITING_AUTH
        )
        assert result.server_url == "https://new.example/mcp"
        fresh = api._db_mcp_server_to_api_mcp_server(
            server, db, request_user=user, include_auth_config=True
        )
        assert fresh.admin_credentials is None
        assert fresh.user_credentials is None
        assert fresh.auth_template is None
        if auth_type != MCPAuthenticationType.NONE:
            assert fresh.connection_status is MCPConnectionStatus.NOT_CONNECTED
        assert "old-secret" not in fresh.model_dump_json()
        reload_sessions.assert_called_once_with({old_user, current_user}, db)
    else:
        delete_users.assert_not_called()
        db.delete.assert_not_called()
        assert server.admin_connection_config is config
        assert server.admin_connection_config_id == 81
        assert result.status == MCPServerStatus.CONNECTED
        reload_sessions.assert_called_once_with({current_user}, db)
    db.commit.assert_called_once()
