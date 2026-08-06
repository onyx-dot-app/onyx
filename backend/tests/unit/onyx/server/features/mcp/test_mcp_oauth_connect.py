import asyncio
import queue
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
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
from onyx.server.features.mcp import api, oauth
from onyx.server.features.mcp.models import MCPUserOAuthConnectRequest


class _Redis:
    def __init__(self) -> None:
        self.auth_urls: queue.Queue[str] = queue.Queue()

    def blpop(self, _keys: list[str], timeout: int) -> tuple[bytes, bytes] | None:
        try:
            value = self.auth_urls.get(timeout=min(timeout, 0.1))
        except queue.Empty:
            return None
        return b"auth_url", value.encode()

    def rpush(self, _key: str, value: str) -> None:
        self.auth_urls.put(value)


class _DiscoveryClient:
    def __init__(self, responses: list[int]) -> None:
        self.responses = iter(responses)
        self.request_urls: list[str] = []

    async def __aenter__(self) -> "_DiscoveryClient":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def send(self, request: httpx.Request) -> httpx.Response:
        self.request_urls.append(str(request.url))
        status = next(self.responses)
        if status == 200:
            return httpx.Response(
                status,
                json={
                    "resource": "https://mcp.example.com/mcp",
                    "authorization_servers": ["https://accounts.example.com"],
                },
                request=request,
            )
        return httpx.Response(status, request=request)


class _OAuthProvider:
    def __init__(self, redis_client: _Redis) -> None:
        self.redis_client = redis_client
        self.challenge: str | None = None

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        response = yield request
        self.challenge = response.headers["WWW-Authenticate"]
        self.redis_client.rpush("auth_url", "https://consent")
        yield request


def _setup_fresh_auto_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SimpleNamespace, SimpleNamespace, _Redis, _OAuthProvider]:
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
    redis_client = _Redis()
    oauth_provider = _OAuthProvider(redis_client)

    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_args: server)
    monkeypatch.setattr(api, "_ensure_mcp_server_owner_or_admin", lambda *_args: None)
    monkeypatch.setattr(api, "get_mcp_auth_template", lambda *_args: None)
    monkeypatch.setattr(api, "get_user_connection_config", lambda *_args: None)
    monkeypatch.setattr(
        api,
        "create_connection_config",
        MagicMock(side_effect=[SimpleNamespace(id=100), SimpleNamespace(id=101)]),
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
    monkeypatch.setattr(api, "make_oauth_provider", lambda *_args: oauth_provider)
    monkeypatch.setattr(
        api, "initialize_mcp_client", AsyncMock(return_value=MagicMock())
    )
    return server, user, redis_client, oauth_provider


def _request(server_id: int) -> MCPUserOAuthConnectRequest:
    return MCPUserOAuthConnectRequest(
        server_id=server_id,
        return_path="/admin/actions/mcp",
        include_resource_param=True,
        oauth_client_id="client-id",
        oauth_client_secret=None,
    )


def test_fresh_auto_discovery_uses_well_known_metadata_to_start_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, user, _, oauth_provider = _setup_fresh_auto_discovery(monkeypatch)
    discovery_client = _DiscoveryClient([404, 200])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda: discovery_client
    )

    response = asyncio.run(
        api._connect_oauth(
            _request(server.id),
            MagicMock(),
            is_admin=True,
            user=cast(User, user),
        )
    )

    assert response.oauth_url == "https://consent"
    assert discovery_client.request_urls == [
        "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
        "https://mcp.example.com/.well-known/oauth-protected-resource",
    ]
    assert oauth_provider.challenge == (
        'Bearer resource_metadata="https://mcp.example.com/'
        '.well-known/oauth-protected-resource"'
    )


def test_fresh_auto_discovery_errors_when_well_known_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, user, _, _ = _setup_fresh_auto_discovery(monkeypatch)
    discovery_client = _DiscoveryClient([404, 404])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda: discovery_client
    )

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            api._connect_oauth(
                _request(server.id),
                MagicMock(),
                is_admin=True,
                user=cast(User, user),
            )
        )

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert "well-known URI" in exc_info.value.detail
