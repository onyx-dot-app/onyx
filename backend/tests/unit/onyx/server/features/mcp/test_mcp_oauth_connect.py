import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from types import SimpleNamespace, TracebackType
from typing import cast
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


class _DiscoveryClient:
    def __init__(self, responses: list[int]) -> None:
        self.responses = iter(responses)
        self.request_urls: list[str] = []

    async def __aenter__(self) -> "_DiscoveryClient":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
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


class _OAuthProvider(httpx.Auth):
    def __init__(
        self, authorization_url_callback: Callable[[str], Awaitable[None]]
    ) -> None:
        self.authorization_url_callback = authorization_url_callback
        self.challenge: str | None = None

    async def publish_redirect(self, auth_url: str) -> None:
        await self.authorization_url_callback(auth_url)

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        response = yield request
        self.challenge = response.headers["WWW-Authenticate"]
        await self.publish_redirect("https://consent")
        request.headers["Authorization"] = "Bearer test-token"
        yield request


class _HangingDiscoveryClient(_DiscoveryClient):
    def __init__(self) -> None:
        super().__init__([])
        self.started = False

    async def send(self, request: httpx.Request) -> httpx.Response:
        del request
        self.started = True
        await asyncio.Event().wait()
        raise RuntimeError("unreachable")


def _setup_fresh_auto_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SimpleNamespace, SimpleNamespace, list[_OAuthProvider]]:
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
    oauth_providers: list[_OAuthProvider] = []

    def make_oauth_provider(
        _mcp_server: object,
        _user_id: str,
        _return_path: str,
        _connection_config_id: int,
        _admin_config_id: int | None,
        authorization_url_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> _OAuthProvider:
        if authorization_url_callback is None:
            raise TypeError("authorization_url_callback is required")
        provider = _OAuthProvider(authorization_url_callback)
        oauth_providers.append(provider)
        return provider

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
    monkeypatch.setattr(oauth, "make_oauth_provider", make_oauth_provider)
    monkeypatch.setattr(
        oauth, "initialize_mcp_client", AsyncMock(return_value=MagicMock())
    )
    return server, user, oauth_providers


def _request(server_id: int) -> MCPUserOAuthConnectRequest:
    return MCPUserOAuthConnectRequest(
        server_id=server_id,
        return_path="/admin/actions/mcp",
        include_resource_param=True,
        oauth_client_id="client-id",
        oauth_client_secret=None,
    )


def test_fresh_auto_discovery_preserves_www_authenticate_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, user, oauth_providers = _setup_fresh_auto_discovery(monkeypatch)
    discovery_factory = MagicMock(
        side_effect=AssertionError("well-known fallback should not run")
    )
    monkeypatch.setattr(oauth, "mcp_ssrf_httpx_client_factory", discovery_factory)

    async def initialize_with_challenge(
        _server_url: str,
        connection_headers: dict[str, str] | None = None,
        transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
        auth: object | None = None,
    ) -> MagicMock:
        del connection_headers, transport
        if not isinstance(auth, _OAuthProvider):
            raise TypeError("expected test OAuth provider")
        await auth.publish_redirect("https://challenge-consent")
        return MagicMock()

    monkeypatch.setattr(oauth, "initialize_mcp_client", initialize_with_challenge)

    response = asyncio.run(
        api._connect_oauth(
            _request(server.id),
            MagicMock(),
            is_admin=True,
            user=cast(User, user),
        )
    )

    assert response.oauth_url == "https://challenge-consent"
    assert oauth_providers[0].challenge is None
    discovery_factory.assert_not_called()


def test_fresh_auto_discovery_uses_well_known_metadata_to_start_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, user, oauth_providers = _setup_fresh_auto_discovery(monkeypatch)
    discovery_client = _DiscoveryClient([404, 200])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda **_kwargs: discovery_client
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
    assert oauth_providers[0].challenge == (
        'Bearer resource_metadata="https://mcp.example.com/'
        '.well-known/oauth-protected-resource"'
    )


def test_fresh_auto_discovery_errors_when_well_known_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, user, _ = _setup_fresh_auto_discovery(monkeypatch)
    discovery_client = _DiscoveryClient([404, 404])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda **_kwargs: discovery_client
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


def test_authenticated_connection_initializes_without_new_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, user, _ = _setup_fresh_auto_discovery(monkeypatch)
    user_config = SimpleNamespace(id=101)
    stored_data = {
        "client_info": {"client_id": "client-id"},
        "headers": {"Authorization": "Bearer stored-token"},
        "tokens": {"access_token": "stored-token", "token_type": "Bearer"},
        "token_expires_at": 1234.0,
    }
    update_connection_config = MagicMock()
    discovery_factory = MagicMock(
        side_effect=AssertionError("authenticated connection should not discover")
    )
    monkeypatch.setattr(api, "get_user_connection_config", lambda *_args: user_config)
    monkeypatch.setattr(
        api, "can_resolve_mcp_credentials", lambda *_args, **_kwargs: True
    )
    monkeypatch.setattr(
        api, "extract_connection_data", lambda *_args, **_kwargs: stored_data
    )
    monkeypatch.setattr(api, "update_connection_config", update_connection_config)
    monkeypatch.setattr(oauth, "mcp_ssrf_httpx_client_factory", discovery_factory)

    response = asyncio.run(
        api._connect_oauth(
            _request(server.id),
            MagicMock(),
            is_admin=True,
            user=cast(User, user),
        )
    )

    assert response.oauth_url == "/admin/actions/mcp"
    discovery_factory.assert_not_called()
    updated_user_data = update_connection_config.call_args.args[2]
    assert updated_user_data["tokens"] == stored_data["tokens"]
    assert updated_user_data["token_expires_at"] == 1234.0


def test_well_known_oauth_flow_has_total_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, user, _ = _setup_fresh_auto_discovery(monkeypatch)
    discovery_client = _HangingDiscoveryClient()
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda **_kwargs: discovery_client
    )
    monkeypatch.setattr(oauth, "STATE_TTL_SECONDS", 0.01)

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            api._connect_oauth(
                _request(server.id),
                MagicMock(),
                is_admin=True,
                user=cast(User, user),
            )
        )

    assert discovery_client.started
    assert "timed out" in exc_info.value.detail
