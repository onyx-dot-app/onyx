import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from types import SimpleNamespace
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
from onyx.server.features.mcp.ssrf import _OAuthChallengeTransport


def _install_discovery_responses(
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[int],
    request_headers: list[httpx.Headers] | None = None,
) -> list[str]:
    remaining_statuses = iter(statuses)
    request_urls: list[str] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        request_urls.append(str(request.url))
        if request_headers is not None:
            request_headers.append(request.headers)
        status = next(remaining_statuses)
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

    def client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            auth=auth,
            headers=headers,
            timeout=timeout,
            transport=httpx.MockTransport(handle_request),
        )

    monkeypatch.setattr(oauth, "mcp_ssrf_httpx_client_factory", client_factory)
    return request_urls


class _OAuthContext:
    token_valid = False

    def is_token_valid(self) -> bool:
        return self.token_valid


class _OAuthProvider(httpx.Auth):
    def __init__(
        self,
        authorization_url_callback: Callable[[str], Awaitable[None]],
        load_stored_tokens: bool,
    ) -> None:
        self.authorization_url_callback = authorization_url_callback
        self.load_stored_tokens = load_stored_tokens
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
        *,
        load_stored_tokens: bool = True,
    ) -> _OAuthProvider:
        if authorization_url_callback is None:
            raise TypeError("authorization_url_callback is required")
        provider = _OAuthProvider(authorization_url_callback, load_stored_tokens)
        providers.append(provider)
        return provider

    initialize = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(oauth, "make_oauth_provider", make_oauth_provider)
    monkeypatch.setattr(oauth, "initialize_mcp_client", initialize)
    return server, providers, initialize


def _connect(
    server: SimpleNamespace,
    *,
    credentials_usable: bool = False,
    connection_headers: dict[str, str] | None = None,
    force_reauthentication: bool = False,
) -> str | None:
    return asyncio.run(
        oauth.connect_auto_discovery_oauth(
            mcp_server=cast(MCPServer, server),
            user_id=str(uuid4()),
            return_path="/admin/actions/mcp",
            connection_config_id=101,
            admin_config_id=100,
            connection_headers=connection_headers or {},
            transport=server.transport,
            credentials_usable=credentials_usable,
            force_reauthentication=force_reauthentication,
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


def test_forced_reauthentication_skips_authenticated_fast_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, providers, initialize = _setup_coordinator(monkeypatch)
    request_urls = _install_discovery_responses(monkeypatch, [200])

    assert (
        _connect(
            server,
            credentials_usable=True,
            connection_headers={
                "Authorization": "Bearer current-token",
                "X-Gateway-Tenant": "tenant-1",
            },
            force_reauthentication=True,
        )
        == "https://consent"
    )
    assert providers[0].load_stored_tokens is False
    assert initialize.await_args is not None
    assert initialize.await_args.kwargs["transport"] is MCPTransport.STREAMABLE_HTTP
    assert initialize.await_args.kwargs["connection_headers"] == {
        "X-Gateway-Tenant": "tenant-1"
    }
    assert request_urls == [
        "https://mcp.example.com/.well-known/oauth-protected-resource/mcp"
    ]


@pytest.mark.parametrize(
    ("transport", "initialization_error"),
    [
        (MCPTransport.STREAMABLE_HTTP, None),
        (MCPTransport.SSE, RuntimeError("SSE endpoint is not streamable")),
    ],
    ids=["public-streamable", "sse-probe-failure"],
)
def test_public_initialization_uses_well_known_metadata(
    monkeypatch: pytest.MonkeyPatch,
    transport: MCPTransport,
    initialization_error: Exception | None,
) -> None:
    server, providers, initialize = _setup_coordinator(monkeypatch, transport)
    initialize.side_effect = initialization_error
    request_headers: list[httpx.Headers] = []
    request_urls = _install_discovery_responses(
        monkeypatch, [404, 200], request_headers
    )

    assert (
        _connect(
            server,
            connection_headers={
                "X-Gateway-Tenant": "tenant-1",
                "Authorization": "Bearer stale-token",
                "Host": "internal.example.com",
            },
        )
        == "https://consent"
    )
    assert request_urls == [
        "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
        "https://mcp.example.com/.well-known/oauth-protected-resource",
    ]
    initialize_call = initialize.await_args
    assert initialize_call is not None
    assert initialize_call.kwargs["transport"] is MCPTransport.STREAMABLE_HTTP
    assert initialize_call.kwargs["connection_headers"] == {
        "X-Gateway-Tenant": "tenant-1",
        "Authorization": "Bearer stale-token",
        "Host": "internal.example.com",
    }
    assert all(headers["X-Gateway-Tenant"] == "tenant-1" for headers in request_headers)
    assert all("Authorization" not in headers for headers in request_headers)
    assert all(headers["Host"] == "mcp.example.com" for headers in request_headers)
    assert providers[0].challenge == (
        'Bearer resource_metadata="https://mcp.example.com/'
        '.well-known/oauth-protected-resource"'
    )


def test_public_initialization_errors_when_metadata_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, _, _ = _setup_coordinator(monkeypatch)
    _install_discovery_responses(monkeypatch, [404, 404])

    with pytest.raises(OnyxError) as exc_info:
        _connect(server)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert "well-known URI" in exc_info.value.detail


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


def test_probe_failure_after_token_refresh_is_not_treated_as_connected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, providers, _ = _setup_coordinator(monkeypatch)

    async def initialize_after_refresh(*_args: object, **_kwargs: object) -> object:
        providers[0].context.token_valid = True
        raise RuntimeError("MCP initialization failed after refresh")

    monkeypatch.setattr(oauth, "initialize_mcp_client", initialize_after_refresh)

    with pytest.raises(RuntimeError, match="initialization failed after refresh"):
        _connect(server)


def test_oauth_challenge_transport_delegates_same_url_posts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        delegated_requests: list[httpx.Request] = []

        def handle_delegated(request: httpx.Request) -> httpx.Response:
            delegated_requests.append(request)
            return httpx.Response(201, request=request)

        transport = _OAuthChallengeTransport(
            "https://mcp.example.com/mcp",
            "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
        )
        monkeypatch.setattr(
            transport, "_delegate", httpx.MockTransport(handle_delegated)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            assert (await client.get("https://mcp.example.com/mcp")).status_code == 401
            assert (await client.get("https://mcp.example.com/mcp")).status_code == 204
            assert (await client.post("https://mcp.example.com/mcp")).status_code == 201

        assert [request.method for request in delegated_requests] == ["POST"]

    asyncio.run(run())


def _request(
    server_id: int, *, force_reauthentication: bool = False
) -> MCPUserOAuthConnectRequest:
    return MCPUserOAuthConnectRequest(
        server_id=server_id,
        return_path="/admin/actions/mcp",
        include_resource_param=True,
        oauth_client_id="client-id",
        oauth_client_secret=None,
        force_reauthentication=force_reauthentication,
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
    monkeypatch.setattr(api, "user_can_authenticate", lambda *_args, **_kwargs: True)
    return server, user, update_connection_config


@pytest.mark.parametrize(
    (
        "expires_at",
        "force_reauthentication",
        "expected_oauth_url",
        "expected_discovery_urls",
    ),
    [
        (4_000_000_000.0, False, "/admin/actions/mcp", []),
        (
            4_000_000_000.0,
            True,
            "https://consent",
            ["https://mcp.example.com/.well-known/oauth-protected-resource/mcp"],
        ),
        (
            1.0,
            False,
            "https://consent",
            ["https://mcp.example.com/.well-known/oauth-protected-resource/mcp"],
        ),
    ],
    ids=["valid", "forced", "expired"],
)
def test_token_expiry_controls_fast_path_without_dropping_oauth_state(
    monkeypatch: pytest.MonkeyPatch,
    expires_at: float,
    force_reauthentication: bool,
    expected_oauth_url: str,
    expected_discovery_urls: list[str],
) -> None:
    stored_data = MCPConnectionData(
        client_info={"client_id": "client-id"},
        headers={"Authorization": "Bearer stored-token"},
        tokens={
            "access_token": "stored-token",
            "refresh_token": "refresh-token",
            "token_type": "Bearer",
        },
        token_expires_at=expires_at,
        metadata={"token_endpoint": "https://accounts.example.com/token"},
    )
    server, user, update_connection_config = _setup_api_connection(
        monkeypatch, stored_data
    )
    request_urls = _install_discovery_responses(monkeypatch, [200])

    response = asyncio.run(
        api._connect_oauth(
            _request(server.id, force_reauthentication=force_reauthentication),
            MagicMock(),
            is_admin=True,
            user=cast(User, user),
        )
    )

    assert response.oauth_url == expected_oauth_url
    assert request_urls == expected_discovery_urls
    updated_data = update_connection_config.call_args.args[2]
    assert updated_data["tokens"] == stored_data["tokens"]
    assert updated_data["token_expires_at"] == stored_data["token_expires_at"]
    assert updated_data["metadata"] == stored_data["metadata"]
