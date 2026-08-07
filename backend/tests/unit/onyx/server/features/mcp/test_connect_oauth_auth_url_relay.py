"""Regression coverage for `_connect_oauth`'s authorization-URL relay: the
connect flow must forward the URL the MCP SDK emits even when the caller's
stored connection config already carries `client_info` plus rendered headers,
because a stored config never proves the handshake will skip authorization.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from onyx.db.enums import MCPAuthenticationType, MCPOAuthProviderMode, MCPTransport
from onyx.server.features.mcp.api import _connect_oauth
from onyx.server.features.mcp.models import (
    MCPUserOAuthConnectRequest,
    MCPUserOAuthConnectResponse,
)

API_MODULE = "onyx.server.features.mcp.api"

AUTH_URL = "https://idp.example.com/authorize?client_id=stored-client-id"
RETURN_PATH = "/chat?mcp=1"

USER_CONFIG = MagicMock(id=99)

# A user who previously completed the handshake: `client_info` seeded from the
# admin config plus the bearer header rendered by the last callback.
CONNECTED_USER_DATA: dict[str, Any] = {
    "client_info": {
        "client_id": "stored-client-id",
        "redirect_uris": ["https://onyx.example.com/mcp/oauth/callback"],
    },
    "headers": {"Authorization": "Bearer stale-access-token"},
}


def _extract_connection_data(config: Any, **_kwargs: Any) -> dict[str, Any]:
    return dict(CONNECTED_USER_DATA) if config is USER_CONFIG else {}


def _mcp_server() -> MagicMock:
    server = MagicMock()
    server.id = 7
    server.name = "example-mcp"
    server.server_url = "https://mcp.example.com/mcp"
    server.auth_type = MCPAuthenticationType.OAUTH
    server.transport = MCPTransport.STREAMABLE_HTTP
    server.oauth_provider_mode = MCPOAuthProviderMode.AUTO_DISCOVERY
    server.admin_connection_config_id = 42
    return server


def _blocking_blpop(*_args: Any, **_kwargs: Any) -> None:
    """Stand in for a Redis list that never receives an auth URL."""
    time.sleep(0.3)
    return None


async def _connect(initialize: Any, blpop: Any) -> MCPUserOAuthConnectResponse:
    redis = MagicMock()
    redis.blpop = blpop
    user = MagicMock(id="user-uuid", email="user@example.com")
    request = MCPUserOAuthConnectRequest(
        server_id=7,
        return_path=RETURN_PATH,
        include_resource_param=False,
        oauth_client_id="stored-client-id",
    )

    with ExitStack() as stack:
        for name, replacement in (
            ("get_mcp_server_by_id", MagicMock(return_value=_mcp_server())),
            ("get_mcp_auth_template", MagicMock(return_value=None)),
            ("get_user_connection_config", MagicMock(return_value=USER_CONFIG)),
            ("extract_connection_data", _extract_connection_data),
            ("update_connection_config", MagicMock()),
            ("make_oauth_provider", MagicMock()),
            ("get_redis_client", MagicMock(return_value=redis)),
            ("initialize_mcp_client", initialize),
        ):
            stack.enter_context(patch(f"{API_MODULE}.{name}", replacement))

        return await _connect_oauth(request, MagicMock(), is_admin=False, user=user)


@pytest.mark.asyncio
async def test_connect_relays_auth_url_for_previously_connected_user() -> None:
    async def hanging_initialize(*_args: Any, **_kwargs: Any) -> Any:
        # The SDK blocks on a callback that only arrives once the user has
        # visited the authorization URL we are expected to return.
        await asyncio.sleep(1)
        raise RuntimeError("Timed out waiting for OAuth callback")

    response = await _connect(
        hanging_initialize, MagicMock(return_value=(b"key", AUTH_URL.encode()))
    )

    assert response.oauth_url == AUTH_URL


@pytest.mark.asyncio
async def test_connect_returns_return_path_when_stored_tokens_still_work() -> None:
    response = await _connect(AsyncMock(return_value=MagicMock()), _blocking_blpop)

    assert response.oauth_url == RETURN_PATH


@pytest.mark.asyncio
async def test_connect_surfaces_init_failure_when_no_auth_url_arrives() -> None:
    async def failing_initialize(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("connection refused")

    with pytest.raises(HTTPException) as exc_info:
        await _connect(failing_initialize, _blocking_blpop)

    assert exc_info.value.status_code == 400
