"""Regression coverage for `_connect_oauth`'s authorization-URL relay: the
connect flow must forward the URL the MCP SDK emits even when the caller's
stored connection config already carries `client_info` plus rendered headers,
because a stored config never proves the handshake will skip authorization.
Without stored tokens the probe also has to leave the stored Authorization
header behind, so a still-accepted bearer cannot masquerade as a connection.
The relay waits in short BLPOP slices so the losing task's cancellation is not
stranded behind a blocking call.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from onyx.db.enums import MCPAuthenticationType, MCPOAuthProviderMode, MCPTransport
from onyx.server.features.mcp.api import AUTH_URL_POLL_SECONDS, _connect_oauth
from onyx.server.features.mcp.models import (
    MCPUserOAuthConnectRequest,
    MCPUserOAuthConnectResponse,
)

API_MODULE = "onyx.server.features.mcp.api"

AUTH_URL = "https://idp.example.com/authorize?client_id=stored-client-id"
RETURN_PATH = "/chat?mcp=1"

USER_CONFIG = MagicMock(id=99)

# A user who previously completed the handshake: `client_info` seeded from the
# admin config, the bearer header left by the last callback, and a header the
# admin's template renders. Tokens are absent — this is the state a connect call
# leaves behind, and the state tool calls treat as unauthenticated.
CONNECTED_USER_DATA: dict[str, Any] = {
    "client_info": {
        "client_id": "stored-client-id",
        "redirect_uris": ["https://onyx.example.com/mcp/oauth/callback"],
    },
    "headers": {
        "Authorization": "Bearer stale-access-token",
        "X-Workspace": "acme",
    },
}


# The same user after a successful handshake: the token is the credential tool
# calls actually use.
TOKENED_USER_DATA: dict[str, Any] = {
    **CONNECTED_USER_DATA,
    "tokens": {"access_token": "live-access-token", "token_type": "Bearer"},
}


def _extract_connection_data(user_data: dict[str, Any]) -> Any:
    def extract(config: Any, **_kwargs: Any) -> dict[str, Any]:
        return dict(user_data) if config is USER_CONFIG else {}

    return extract


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


async def _connect(
    initialize: Any,
    blpop: Any,
    user_data: dict[str, Any] = CONNECTED_USER_DATA,
) -> MCPUserOAuthConnectResponse:
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
            ("extract_connection_data", _extract_connection_data(user_data)),
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
    probes: list[dict[str, str]] = []

    async def succeeding_initialize(*_args: Any, **kwargs: Any) -> Any:
        probes.append(dict(kwargs["connection_headers"]))
        return MagicMock()

    response = await _connect(
        succeeding_initialize, _blocking_blpop, user_data=TOKENED_USER_DATA
    )

    assert response.oauth_url == RETURN_PATH
    # Stored tokens make the stored headers meaningful, so the probe keeps them.
    assert probes == [TOKENED_USER_DATA["headers"]]


@pytest.mark.asyncio
async def test_connect_probes_without_the_stored_bearer_when_tokens_are_missing() -> (
    None
):
    probes: list[dict[str, str]] = []

    async def initialize_accepting_any_bearer(*_args: Any, **kwargs: Any) -> Any:
        headers = dict(kwargs["connection_headers"])
        probes.append(headers)
        if "Authorization" in headers:
            # A provider whose access tokens do not expire answers the stored
            # bearer, so the handshake reports a connection and never redirects.
            return MagicMock()
        await asyncio.sleep(5)
        raise RuntimeError("Timed out waiting for OAuth callback")

    def blpop_after_a_short_slice(_keys: Any, _timeout: int = 0) -> tuple[bytes, bytes]:
        time.sleep(0.05)
        return (b"key", AUTH_URL.encode())

    response = await _connect(
        initialize_accepting_any_bearer, blpop_after_a_short_slice
    )

    assert response.oauth_url == AUTH_URL
    assert probes == [{"X-Workspace": "acme"}]


@pytest.mark.asyncio
async def test_connect_stops_polling_for_the_auth_url_once_initialization_wins() -> (
    None
):
    slice_starts: list[float] = []

    def blpop_empty_slice(_keys: Any, _timeout: int = 0) -> None:
        slice_starts.append(time.monotonic())
        time.sleep(0.1)
        return None

    async def slow_initialize(*_args: Any, **_kwargs: Any) -> Any:
        await asyncio.sleep(0.35)
        return MagicMock()

    response = await _connect(slow_initialize, blpop_empty_slice, TOKENED_USER_DATA)

    assert response.oauth_url == RETURN_PATH
    slices_at_return = len(slice_starts)
    assert slices_at_return >= 2

    await asyncio.sleep(0.4)
    # Cancellation lands between slices, so only the slice already in flight runs
    # on — the wait does not linger for the rest of the window.
    assert len(slice_starts) <= slices_at_return + 1


@pytest.mark.asyncio
async def test_connect_surfaces_init_failure_when_no_auth_url_arrives() -> None:
    async def failing_initialize(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("connection refused")

    with pytest.raises(HTTPException) as exc_info:
        await _connect(failing_initialize, _blocking_blpop)

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_connect_waits_for_auth_url_in_short_blocking_slices() -> None:
    timeouts: list[int] = []

    def blpop_after_a_few_slices(
        _keys: Any, timeout: int = 0
    ) -> tuple[bytes, bytes] | None:
        timeouts.append(timeout)
        if len(timeouts) < 3:
            return None
        return (b"key", AUTH_URL.encode())

    async def hanging_initialize(*_args: Any, **_kwargs: Any) -> Any:
        await asyncio.sleep(5)
        raise RuntimeError("Timed out waiting for OAuth callback")

    response = await _connect(hanging_initialize, blpop_after_a_few_slices)

    assert response.oauth_url == AUTH_URL
    # Several bounded waits rather than one block spanning the whole window.
    assert len(timeouts) == 3
    assert max(timeouts) <= AUTH_URL_POLL_SECONDS
