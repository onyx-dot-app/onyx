import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from mcp.client.auth.oauth2 import OAuthContext
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    ProtectedResourceMetadata,
)

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.db.models import MCPServer
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import oauth, oauth_flow
from onyx.server.features.mcp.models import (
    MCPOAuthFlowState,
    MCPPendingOAuthAuthorization,
)

_AUTHORIZATION_URL = "https://accounts.example.com/authorize"
_TOKEN_URL = "https://accounts.example.com/token"
_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"


def _client_information(client_id: str = "client-id") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret=f"{client_id}-secret",
        redirect_uris=[_REDIRECT_URI],
        token_endpoint_auth_method="client_secret_post",
    )


def _server(
    transport: MCPTransport = MCPTransport.STREAMABLE_HTTP,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        name="Protected MCP",
        server_url="https://mcp.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=transport,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_authorization_endpoint=None,
        oauth_token_endpoint=None,
        oauth_scopes_override=None,
        oauth_additional_auth_params=None,
        admin_connection_config=None,
        admin_connection_config_id=100,
    )


def _flow(
    state: str,
    *,
    client_id: str = "client-id",
) -> MCPOAuthFlowState:
    mcp_server = cast(MCPServer, _server())
    client_information = _client_information(client_id)
    code_verifier = f"{state}-verifier"
    return MCPOAuthFlowState(
        server_id=mcp_server.id,
        connection_config_id=101,
        return_path="/admin/actions/mcp",
        code_verifier=code_verifier,
        redirect_uri=_REDIRECT_URI,
        server_snapshot=oauth_flow._snapshot_server_configuration(mcp_server),
        connection_headers_fingerprint=(
            oauth_flow.mcp_oauth_connection_headers_fingerprint({})
        ),
        client_information_fingerprint=(
            oauth_flow.mcp_oauth_client_information_fingerprint(
                client_information,
            )
        ),
        protected_resource_metadata=ProtectedResourceMetadata(
            resource="https://mcp.example.com/mcp",
            authorization_servers=["https://accounts.example.com"],
        ),
        oauth_metadata=OAuthMetadata(
            issuer="https://accounts.example.com",
            authorization_endpoint=_AUTHORIZATION_URL,
            token_endpoint=_TOKEN_URL,
        ),
        authorization_server_url="https://accounts.example.com",
        protocol_version="2025-06-18",
        scope="files:read",
    )


class _FakeOAuthContext:
    def __init__(self) -> None:
        self.protected_resource_metadata = ProtectedResourceMetadata(
            resource="https://mcp.example.com/mcp",
            authorization_servers=["https://accounts.example.com"],
        )
        self.oauth_metadata = OAuthMetadata(
            issuer="https://accounts.example.com",
            authorization_endpoint=_AUTHORIZATION_URL,
            token_endpoint=_TOKEN_URL,
        )
        self.auth_server_url = "https://accounts.example.com"
        self.protocol_version = "2025-06-18"
        self.client_metadata = SimpleNamespace(
            scope="files:read", redirect_uris=[oauth.AnyUrl(_REDIRECT_URI)]
        )
        self.client_info = _client_information()
        self.token_valid = False

    def is_token_valid(self) -> bool:
        return self.token_valid


class _FakeOAuthProvider(httpx.Auth):
    def __init__(
        self,
        handler: Callable[
            [MCPPendingOAuthAuthorization, OAuthContext], Awaitable[None]
        ],
        load_stored_tokens: bool,
    ) -> None:
        self.handler = handler
        self.load_stored_tokens = load_stored_tokens
        self.context = _FakeOAuthContext()
        self.challenge: str | None = None

    async def require_authorization(self) -> None:
        authorization = MCPPendingOAuthAuthorization(
            authorization_url="https://accounts.example.com/consent",
            state="flow-state",
            code_verifier="v" * 128,
        )
        await self.handler(authorization, cast(OAuthContext, self.context))
        raise oauth.OAuthAuthorizationRequired(authorization)

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        response = yield request
        self.challenge = response.headers["WWW-Authenticate"]
        await self.require_authorization()
        raise AssertionError("authorization handoff must unwind the request")


def _setup_flow_coordinator(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[_FakeOAuthProvider], AsyncMock, MagicMock]:
    providers: list[_FakeOAuthProvider] = []

    def make_oauth_provider(
        _mcp_server: object,
        _connection_config_id: int,
        _admin_config_id: int | None,
        *,
        load_stored_tokens: bool = True,
        authorization_request_handler: Callable[
            [MCPPendingOAuthAuthorization, OAuthContext], Awaitable[None]
        ]
        | None = None,
    ) -> _FakeOAuthProvider:
        assert authorization_request_handler is not None
        provider = _FakeOAuthProvider(authorization_request_handler, load_stored_tokens)
        providers.append(provider)
        return provider

    initialize = AsyncMock()
    attempt_store = MagicMock()
    monkeypatch.setattr(oauth_flow, "make_oauth_provider", make_oauth_provider)
    monkeypatch.setattr(oauth_flow, "initialize_mcp_client", initialize)
    monkeypatch.setattr(oauth_flow, "mcp_oauth_attempt_store", lambda: attempt_store)
    return providers, initialize, attempt_store


def _start_flow(
    server: SimpleNamespace,
    *,
    credentials_usable: bool = False,
    force_reauthentication: bool = False,
    connection_headers: dict[str, str] | None = None,
) -> oauth_flow.OAuthStartResult:
    return asyncio.run(
        oauth_flow.start_auto_discovery_oauth_flow(
            mcp_server=cast(MCPServer, server),
            user_id="user-1",
            return_path="/admin/actions/mcp",
            connection_config_id=101,
            shared_client_config_id=100,
            connection_headers=connection_headers or {},
            transport=server.transport,
            credentials_usable=credentials_usable,
            force_reauthentication=force_reauthentication,
        )
    )


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

    def client_factory(**kwargs: object) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=cast(httpx.Timeout | None, kwargs.get("timeout")),
            transport=httpx.MockTransport(handle_request),
        )

    monkeypatch.setattr(oauth_flow, "mcp_ssrf_httpx_client_factory", client_factory)
    return request_urls


def test_challenge_stores_resumable_flow_and_skips_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers, initialize, attempt_store = _setup_flow_coordinator(monkeypatch)

    async def initialize_with_challenge(*_args: object, **_kwargs: object) -> object:
        await providers[0].require_authorization()
        raise AssertionError("authorization handoff must unwind the request")

    initialize.side_effect = initialize_with_challenge
    fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))
    monkeypatch.setattr(oauth_flow, "_start_oauth_from_well_known_metadata", fallback)

    assert _start_flow(_server()) == oauth_flow.OAuthAuthorizationRedirect(
        "https://accounts.example.com/consent"
    )
    attempt_store.store.assert_called_once()
    store_call = attempt_store.store.call_args
    assert store_call.kwargs["owner_id"] == "user-1"
    assert store_call.kwargs["state"] == "flow-state"
    stored_flow = store_call.kwargs["payload"]
    assert stored_flow.connection_config_id == 101
    assert stored_flow.code_verifier == "v" * 128
    assert stored_flow.server_snapshot.server_url == "https://mcp.example.com/mcp"
    fallback.assert_not_awaited()


def test_forced_reauthentication_ignores_tokens_and_strips_bearer_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers, initialize, _ = _setup_flow_coordinator(monkeypatch)

    async def initialize_with_challenge(*_args: object, **_kwargs: object) -> object:
        await providers[0].require_authorization()
        raise AssertionError("unreachable")

    initialize.side_effect = initialize_with_challenge

    result = _start_flow(
        _server(),
        credentials_usable=True,
        force_reauthentication=True,
        connection_headers={
            "Authorization": "Bearer old-token",
            "X-Gateway-Tenant": "tenant-1",
        },
    )
    assert result == oauth_flow.OAuthAuthorizationRedirect(
        "https://accounts.example.com/consent"
    )
    assert providers[0].load_stored_tokens is False
    initialize_call = initialize.await_args
    assert initialize_call is not None
    assert initialize_call.kwargs["transport"] is MCPTransport.STREAMABLE_HTTP
    assert initialize_call.kwargs["connection_headers"] == {
        "X-Gateway-Tenant": "tenant-1"
    }


@pytest.mark.parametrize(
    ("transport", "initialization_error"),
    [
        (MCPTransport.STREAMABLE_HTTP, None),
        (MCPTransport.SSE, RuntimeError("SSE endpoint is not streamable")),
    ],
    ids=["public-streamable", "sse-probe-failure"],
)
def test_public_initialization_uses_safe_well_known_discovery(
    monkeypatch: pytest.MonkeyPatch,
    transport: MCPTransport,
    initialization_error: Exception | None,
) -> None:
    providers, initialize, _ = _setup_flow_coordinator(monkeypatch)
    initialize.side_effect = initialization_error
    request_headers: list[httpx.Headers] = []
    request_urls = _install_discovery_responses(
        monkeypatch, [404, 200], request_headers
    )

    result = _start_flow(
        _server(transport),
        connection_headers={
            "X-Gateway-Tenant": "tenant-1",
            "Authorization": "Bearer stale-token",
            "Host": "internal.example.com",
        },
    )
    assert result == oauth_flow.OAuthAuthorizationRedirect(
        "https://accounts.example.com/consent"
    )
    assert request_urls == [
        "https://mcp.example.com/.well-known/oauth-protected-resource/mcp",
        "https://mcp.example.com/.well-known/oauth-protected-resource",
    ]
    assert all(headers["X-Gateway-Tenant"] == "tenant-1" for headers in request_headers)
    assert all("Authorization" not in headers for headers in request_headers)
    assert all(headers["Host"] == "mcp.example.com" for headers in request_headers)
    assert providers[0].challenge == (
        'Bearer resource_metadata="https://mcp.example.com/'
        '.well-known/oauth-protected-resource"'
    )


def test_public_initialization_rejects_missing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup_flow_coordinator(monkeypatch)
    _install_discovery_responses(monkeypatch, [404, 404])

    with pytest.raises(OnyxError) as exc_info:
        _start_flow(_server())

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert "well-known URI" in exc_info.value.detail


def test_failure_after_token_refresh_does_not_start_browser_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers, initialize, _ = _setup_flow_coordinator(monkeypatch)
    fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))
    monkeypatch.setattr(oauth_flow, "_start_oauth_from_well_known_metadata", fallback)

    async def initialize_after_refresh(*_args: object, **_kwargs: object) -> object:
        providers[0].context.token_valid = True
        raise RuntimeError("MCP initialization failed after refresh")

    initialize.side_effect = initialize_after_refresh

    with pytest.raises(RuntimeError, match="initialization failed after refresh"):
        _start_flow(_server())
    fallback.assert_not_awaited()


def test_authenticated_failure_does_not_start_browser_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, initialize, _ = _setup_flow_coordinator(monkeypatch)
    initialize.side_effect = RuntimeError("authenticated MCP initialization failed")
    fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))
    monkeypatch.setattr(oauth_flow, "_start_oauth_from_well_known_metadata", fallback)

    with pytest.raises(RuntimeError, match="authenticated MCP initialization failed"):
        _start_flow(_server(), credentials_usable=True)
    fallback.assert_not_awaited()


def test_valid_stored_credentials_return_an_explicit_authenticated_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers, initialize, _ = _setup_flow_coordinator(monkeypatch)

    async def initialize_with_valid_token(*_args: object, **_kwargs: object) -> object:
        providers[0].context.token_valid = True
        return object()

    initialize.side_effect = initialize_with_valid_token
    fallback = AsyncMock(side_effect=AssertionError("fallback should not run"))
    monkeypatch.setattr(oauth_flow, "_start_oauth_from_well_known_metadata", fallback)

    assert _start_flow(_server(), credentials_usable=True) == (
        oauth_flow.OAuthAlreadyAuthenticated()
    )
    fallback.assert_not_awaited()


def test_discovery_timeout_cancels_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    _, initialize, _ = _setup_flow_coordinator(monkeypatch)
    probe_cancelled = False

    async def initialize_forever(*_args: object, **_kwargs: object) -> object:
        nonlocal probe_cancelled
        try:
            await asyncio.Event().wait()
        finally:
            probe_cancelled = True

    initialize.side_effect = initialize_forever
    monkeypatch.setattr(oauth_flow, "OAUTH_HTTP_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(OnyxError, match="Timed out during MCP OAuth discovery"):
        _start_flow(_server())
    assert probe_cancelled


def test_mixed_exception_group_does_not_hide_real_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, initialize, _ = _setup_flow_coordinator(monkeypatch)
    authorization = MCPPendingOAuthAuthorization(
        authorization_url="https://accounts.example.com/consent",
        state="flow-state",
        code_verifier="v" * 128,
    )
    mixed_group = ExceptionGroup(
        "handoff plus cleanup failure",
        [
            oauth.OAuthAuthorizationRequired(authorization),
            RuntimeError("cleanup failed"),
        ],
    )
    initialize.side_effect = mixed_group

    with pytest.raises(ExceptionGroup, match="cleanup failure") as exc_info:
        _start_flow(_server())
    assert len(exc_info.value.exceptions) == 1
    assert isinstance(exc_info.value.exceptions[0], RuntimeError)
    assert str(exc_info.value.exceptions[0]) == "cleanup failed"


def test_nested_single_authorization_handoff_is_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, initialize, _ = _setup_flow_coordinator(monkeypatch)
    authorization = MCPPendingOAuthAuthorization(
        authorization_url="https://accounts.example.com/consent",
        state="flow-state",
        code_verifier="v" * 128,
    )
    initialize.side_effect = ExceptionGroup(
        "outer cleanup group",
        [
            ExceptionGroup(
                "inner task group",
                [oauth.OAuthAuthorizationRequired(authorization)],
            )
        ],
    )

    assert _start_flow(_server()) == oauth_flow.OAuthAuthorizationRedirect(
        authorization.authorization_url
    )


def test_concurrent_client_registration_retries_with_the_elected_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = oauth_flow.OAuthAuthorizationRedirect(
        "https://accounts.example.com/consent"
    )
    start_once = AsyncMock(
        side_effect=[oauth.MCPClientRegistrationConflict(), completed]
    )
    monkeypatch.setattr(
        oauth_flow,
        "_start_auto_discovery_oauth_flow_once",
        start_once,
    )

    assert _start_flow(_server()) == completed
    assert start_once.await_count == 2


def test_multiple_authorization_handoffs_fail_as_an_ordinary_application_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, initialize, _ = _setup_flow_coordinator(monkeypatch)
    authorizations = [
        MCPPendingOAuthAuthorization(
            authorization_url=f"https://accounts.example.com/consent/{state}",
            state=state,
            code_verifier="v" * 128,
        )
        for state in ("first", "second")
    ]
    initialize.side_effect = ExceptionGroup(
        "ambiguous handoff",
        [
            oauth.OAuthAuthorizationRequired(authorization)
            for authorization in authorizations
        ],
    )

    with pytest.raises(OnyxError, match="multiple authorization redirects"):
        _start_flow(_server())


def test_reverse_order_completions_restore_their_own_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers: list[oauth.OnyxOAuthClientProvider] = []
    exchanges: list[AsyncMock] = []

    def make_provider(
        *_args: object, **_kwargs: object
    ) -> oauth.OnyxOAuthClientProvider:
        provider = oauth.OnyxOAuthClientProvider(
            server_url="https://mcp.example.com/mcp",
            client_metadata=oauth.OAuthClientMetadata(
                client_name="Onyx",
                redirect_uris=[oauth.AnyUrl(_REDIRECT_URI)],
            ),
            storage=MagicMock(),
            refresh_log_context={
                "mcp_server_id": 42,
                "mcp_server_name": "Protected MCP",
                "connection_config_id": 101,
                "transport": "STREAMABLE_HTTP",
                "oauth_provider_mode": "AUTO_DISCOVERY",
            },
        )
        exchange = AsyncMock()
        monkeypatch.setattr(provider, "complete_authorization_code_exchange", exchange)
        providers.append(provider)
        exchanges.append(exchange)
        return provider

    monkeypatch.setattr(oauth_flow, "make_oauth_provider", make_provider)
    first_flow = _flow("first-state", client_id="first-registration")
    second_flow = _flow("second-state", client_id="second-registration")

    asyncio.run(
        oauth_flow.complete_mcp_oauth_flow(
            second_flow,
            cast(MCPServer, _server()),
            _client_information("second-registration"),
            "second-code",
        )
    )
    asyncio.run(
        oauth_flow.complete_mcp_oauth_flow(
            first_flow,
            cast(MCPServer, _server()),
            _client_information("first-registration"),
            "first-code",
        )
    )

    assert providers[0].context.client_info == _client_information(
        "second-registration"
    )
    assert providers[1].context.client_info == _client_information("first-registration")
    exchanges[0].assert_awaited_once_with(
        "second-code", "second-state-verifier", resource=None
    )
    exchanges[1].assert_awaited_once_with(
        "first-code", "first-state-verifier", resource=None
    )
