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
from onyx.db.models import MCPServer, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api, oauth
from onyx.server.features.mcp.models import (
    MCPConnectionData,
    MCPUserOAuthConnectRequest,
)


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


class _OAuthContext:
    def is_token_valid(self) -> bool:
        return False


class _OAuthProvider(httpx.Auth):
    def __init__(
        self, authorization_url_callback: Callable[[str], Awaitable[None]]
    ) -> None:
        self.authorization_url_callback = authorization_url_callback
        self.context = _OAuthContext()
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


def _server(transport: MCPTransport = MCPTransport.STREAMABLE_HTTP) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        name="Public MCP",
        server_url="https://mcp.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=transport,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        admin_connection_config=None,
        admin_connection_config_id=None,
    )


def _setup_coordinator(
    monkeypatch: pytest.MonkeyPatch,
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
) -> tuple[SimpleNamespace, list[_OAuthProvider], AsyncMock]:
    server = _server(transport)
    providers: list[_OAuthProvider] = []

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
        providers.append(provider)
        return provider

    initialize = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(oauth, "make_oauth_provider", make_oauth_provider)
    monkeypatch.setattr(oauth, "initialize_mcp_client", initialize)
    return server, providers, initialize


def _connect(server: SimpleNamespace, *, is_authenticated: bool = False) -> str | None:
    return asyncio.run(
        oauth.connect_auto_discovery_oauth(
            mcp_server=cast(MCPServer, server),
            user_id=str(uuid4()),
            return_path="/admin/actions/mcp",
            connection_config_id=101,
            admin_config_id=100,
            connection_headers={},
            transport=server.transport,
            is_authenticated=is_authenticated,
        )
    )


def test_challenge_redirect_skips_well_known_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, providers, _ = _setup_coordinator(monkeypatch)
    discovery_factory = MagicMock(
        side_effect=AssertionError("well-known fallback should not run")
    )
    monkeypatch.setattr(oauth, "mcp_ssrf_httpx_client_factory", discovery_factory)

    async def initialize_with_challenge(
        _server_url: str,
        connection_headers: dict[str, str] | None = None,
        transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
        auth: object | None = None,
    ) -> object:
        del connection_headers, transport
        if not isinstance(auth, _OAuthProvider):
            raise TypeError("expected test OAuth provider")
        await auth.publish_redirect("https://challenge-consent")
        await asyncio.Event().wait()
        raise RuntimeError("unreachable")

    monkeypatch.setattr(oauth, "initialize_mcp_client", initialize_with_challenge)

    assert _connect(server) == "https://challenge-consent"
    assert providers[0].challenge is None
    discovery_factory.assert_not_called()


def test_public_initialization_uses_path_then_root_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, providers, _ = _setup_coordinator(monkeypatch)
    discovery_client = _DiscoveryClient([404, 200])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda **_kwargs: discovery_client
    )

    assert _connect(server) == "https://consent"
    assert discovery_client.request_urls == [
        "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
        "https://mcp.example.com/.well-known/oauth-protected-resource",
    ]
    assert providers[0].challenge == (
        'Bearer resource_metadata="https://mcp.example.com/'
        '.well-known/oauth-protected-resource"'
    )


def test_public_initialization_errors_when_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = _setup_coordinator(monkeypatch)
    discovery_client = _DiscoveryClient([404, 404])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda **_kwargs: discovery_client
    )

    with pytest.raises(OnyxError) as exc_info:
        _connect(server)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert "well-known URI" in exc_info.value.detail


def test_fresh_sse_connection_uses_auth_capable_probe_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, initialize = _setup_coordinator(monkeypatch, MCPTransport.SSE)
    initialize.side_effect = RuntimeError("SSE endpoint is not streamable")
    discovery_client = _DiscoveryClient([200])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda **_kwargs: discovery_client
    )

    assert _connect(server) == "https://consent"
    initialize_call = initialize.await_args
    assert initialize_call is not None
    assert initialize_call.kwargs["transport"] is MCPTransport.STREAMABLE_HTTP


def test_oauth_redirect_wait_is_bounded_and_cancels_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = _setup_coordinator(monkeypatch)
    probe_started = asyncio.Event()
    probe_cancelled = False

    async def initialize_forever(*_args: object, **_kwargs: object) -> object:
        nonlocal probe_cancelled
        probe_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            probe_cancelled = True
        raise RuntimeError("unreachable")

    monkeypatch.setattr(oauth, "initialize_mcp_client", initialize_forever)
    monkeypatch.setattr(oauth, "OAUTH_WAIT_SECONDS", 0.01)

    with pytest.raises(OnyxError, match="Timed out waiting"):
        _connect(server)

    assert probe_started.is_set()
    assert probe_cancelled


def _request(server_id: int) -> MCPUserOAuthConnectRequest:
    return MCPUserOAuthConnectRequest(
        server_id=server_id,
        return_path="/admin/actions/mcp",
        include_resource_param=True,
        oauth_client_id="client-id",
        oauth_client_secret=None,
    )


def _setup_api_connection(
    monkeypatch: pytest.MonkeyPatch,
    stored_data: MCPConnectionData,
) -> tuple[SimpleNamespace, SimpleNamespace, MagicMock]:
    server, _, _ = _setup_coordinator(monkeypatch)
    user = SimpleNamespace(id=uuid4(), email="user@example.com")
    user_config = SimpleNamespace(id=101)
    update_connection_config = MagicMock()

    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_args: server)
    monkeypatch.setattr(api, "_ensure_mcp_server_owner_or_admin", lambda *_args: None)
    monkeypatch.setattr(api, "get_mcp_auth_template", lambda *_args: None)
    monkeypatch.setattr(api, "get_user_connection_config", lambda *_args: user_config)
    monkeypatch.setattr(
        api, "create_connection_config", MagicMock(return_value=SimpleNamespace(id=100))
    )
    monkeypatch.setattr(
        api, "extract_connection_data", lambda *_args, **_kwargs: stored_data
    )
    monkeypatch.setattr(api, "update_connection_config", update_connection_config)
    monkeypatch.setattr(
        api, "can_resolve_mcp_credentials", lambda *_args, **_kwargs: True
    )
    return server, user, update_connection_config


def test_valid_connection_preserves_oauth_state_without_new_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored_data = MCPConnectionData(
        client_info={"client_id": "client-id"},
        headers={"Authorization": "Bearer stored-token"},
        tokens={"access_token": "stored-token", "token_type": "Bearer"},
        token_expires_at=4_000_000_000.0,
        metadata={"token_endpoint": "https://accounts.example.com/token"},
    )
    server, user, update_connection_config = _setup_api_connection(
        monkeypatch, stored_data
    )
    discovery_factory = MagicMock(
        side_effect=AssertionError("authenticated connection should not discover")
    )
    monkeypatch.setattr(oauth, "mcp_ssrf_httpx_client_factory", discovery_factory)

    response = asyncio.run(
        api._connect_oauth(
            _request(server.id), MagicMock(), is_admin=True, user=cast(User, user)
        )
    )

    assert response.oauth_url == "/admin/actions/mcp"
    discovery_factory.assert_not_called()
    updated_data = update_connection_config.call_args.args[2]
    assert updated_data["tokens"] == stored_data["tokens"]
    assert updated_data["token_expires_at"] == stored_data["token_expires_at"]
    assert updated_data["metadata"] == stored_data["metadata"]


def test_expired_connection_preserves_refresh_state_but_requires_oauth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored_data = MCPConnectionData(
        client_info={"client_id": "client-id"},
        headers={"Authorization": "Bearer expired-token"},
        tokens={
            "access_token": "expired-token",
            "refresh_token": "refresh-token",
            "token_type": "Bearer",
        },
        token_expires_at=1.0,
        metadata={"token_endpoint": "https://accounts.example.com/token"},
    )
    server, user, update_connection_config = _setup_api_connection(
        monkeypatch, stored_data
    )
    discovery_client = _DiscoveryClient([200])
    monkeypatch.setattr(
        oauth, "mcp_ssrf_httpx_client_factory", lambda **_kwargs: discovery_client
    )

    response = asyncio.run(
        api._connect_oauth(
            _request(server.id), MagicMock(), is_admin=True, user=cast(User, user)
        )
    )

    assert response.oauth_url == "https://consent"
    updated_data = update_connection_config.call_args.args[2]
    assert updated_data["tokens"] == stored_data["tokens"]
    assert updated_data["token_expires_at"] == stored_data["token_expires_at"]
    assert updated_data["metadata"] == stored_data["metadata"]
