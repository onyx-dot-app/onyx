import asyncio
import time
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.server.features.mcp.models import MCPUserOAuthConnectRequest


def test_public_initialization_does_not_complete_fresh_oauth_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = SimpleNamespace(
        id=42,
        name="Public MCP",
        server_url="https://mcp.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=MCPTransport.STREAMABLE_HTTP,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        admin_connection_config=None,
        admin_connection_config_id=None,
    )
    user = SimpleNamespace(id=uuid4(), email="user@example.com")
    admin_config = SimpleNamespace(id=100)
    user_config = SimpleNamespace(id=101)
    redis_client = MagicMock()
    redis_client.blpop.side_effect = lambda *_args, **_kwargs: time.sleep(0.05)

    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_args: server)
    monkeypatch.setattr(api, "_ensure_mcp_server_owner_or_admin", lambda *_args: None)
    monkeypatch.setattr(api, "get_mcp_auth_template", lambda *_args: None)
    monkeypatch.setattr(api, "get_user_connection_config", lambda *_args: None)
    monkeypatch.setattr(
        api,
        "create_connection_config",
        MagicMock(side_effect=[admin_config, user_config]),
    )
    monkeypatch.setattr(
        api,
        "extract_connection_data",
        lambda *_args, **_kwargs: {
            "client_info": {"client_id": "client-id"},
            "headers": {},
        },
    )
    monkeypatch.setattr(api, "get_redis_client", lambda: redis_client)
    monkeypatch.setattr(api, "make_oauth_provider", lambda *_args: MagicMock())
    initialize = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(api, "initialize_mcp_client", initialize)

    request = MCPUserOAuthConnectRequest(
        server_id=server.id,
        return_path="/admin/actions/mcp",
        include_resource_param=True,
        oauth_client_id="client-id",
    )

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            api._connect_oauth(
                request,
                MagicMock(),
                is_admin=True,
                user=cast(User, user),
            )
        )

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert "permits unauthenticated initialization" in exc_info.value.detail
    initialize.assert_awaited_once()
