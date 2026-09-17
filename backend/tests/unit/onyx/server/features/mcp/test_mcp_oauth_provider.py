import asyncio
import base64
import hashlib
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    OAuthToken,
    ProtectedResourceMetadata,
)

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import oauth
from onyx.utils.url import SSRFException

_AUTHORIZATION_URL = "https://accounts.example.com/authorize"
_TOKEN_URL = "https://accounts.example.com/token"
_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"


def _client_information(
    client_id: str = "client-id",
    token_endpoint_auth_method: Literal[
        "client_secret_post", "client_secret_basic"
    ] = "client_secret_post",
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret=f"{client_id}-secret",
        redirect_uris=[_REDIRECT_URI],
        token_endpoint_auth_method=token_endpoint_auth_method,
    )


class _MemoryTokenStorage:
    def __init__(self) -> None:
        self.tokens: OAuthToken | None = None
        self.client_info = _client_information()

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


class _RecordingAuthorizationStorage(oauth.OnyxTokenStorage):
    def __init__(
        self,
        token_endpoint_auth_method: Literal[
            "client_secret_post", "client_secret_basic"
        ] = "client_secret_post",
    ) -> None:
        super().__init__(connection_config_id=101)
        self.tokens: OAuthToken | None = None
        self.client_info = _client_information(
            token_endpoint_auth_method=token_endpoint_auth_method
        )
        self.persisted_client_information: OAuthClientInformationFull | None = None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        del tokens
        raise AssertionError("authorization must persist registration with its tokens")

    async def set_authorization_result(
        self,
        tokens: OAuthToken,
        client_information: OAuthClientInformationFull,
    ) -> None:
        self.tokens = tokens
        self.persisted_client_information = client_information


def _provider(
    storage: _MemoryTokenStorage | _RecordingAuthorizationStorage,
    *,
    authorization_request_handler: oauth.AuthorizationRequestHandler | None = None,
) -> oauth.OnyxOAuthClientProvider:
    provider = oauth.OnyxOAuthClientProvider(
        server_url="https://mcp.example.com/mcp",
        client_metadata=oauth.OAuthClientMetadata(
            client_name="Onyx",
            redirect_uris=[oauth.AnyUrl(_REDIRECT_URI)],
            scope="files:read offline_access",
        ),
        storage=storage,
        refresh_log_context={
            "mcp_server_id": 42,
            "mcp_server_name": "Protected MCP",
            "connection_config_id": 101,
            "transport": "STREAMABLE_HTTP",
            "oauth_provider_mode": "AUTO_DISCOVERY",
        },
        authorization_request_handler=authorization_request_handler,
    )
    provider.context.client_info = storage.client_info
    provider.context.protected_resource_metadata = ProtectedResourceMetadata(
        resource="https://mcp.example.com/mcp",
        authorization_servers=["https://accounts.example.com"],
    )
    provider.context.oauth_metadata = OAuthMetadata(
        issuer="https://accounts.example.com",
        authorization_endpoint=_AUTHORIZATION_URL,
        token_endpoint=_TOKEN_URL,
    )
    return provider


def _authorization_required_response(request: httpx.Request) -> httpx.Response:
    if "oauth-protected-resource" in request.url.path:
        return httpx.Response(
            200,
            json={
                "resource": "https://mcp.example.com/mcp",
                "authorization_servers": ["https://accounts.example.com"],
            },
            request=request,
        )
    if "oauth-authorization-server" in request.url.path:
        return httpx.Response(
            200,
            json={
                "issuer": "https://accounts.example.com",
                "authorization_endpoint": _AUTHORIZATION_URL,
                "token_endpoint": _TOKEN_URL,
            },
            request=request,
        )
    assert request.url.path == "/mcp"
    return httpx.Response(
        401,
        headers={
            "WWW-Authenticate": (
                'Bearer resource_metadata="https://mcp.example.com/'
                '.well-known/oauth-protected-resource/mcp"'
            )
        },
        request=request,
    )


def test_authorization_request_binds_state_pkce_scope_and_resource() -> None:
    provider = _provider(_MemoryTokenStorage())

    request = provider.build_resumable_authorization_request()

    query = parse_qs(urlparse(request.authorization_url).query)
    expected_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(request.code_verifier.encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    assert query["state"] == [request.state]
    assert query["code_challenge"] == [expected_challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == ["files:read offline_access"]
    assert query["resource"] == ["https://mcp.example.com/mcp"]


@pytest.mark.parametrize(
    "token_endpoint_auth_method",
    ["client_secret_post", "client_secret_basic"],
)
def test_authorization_code_exchange_honors_client_auth_method_and_persists(
    monkeypatch: pytest.MonkeyPatch,
    token_endpoint_auth_method: Literal["client_secret_post", "client_secret_basic"],
) -> None:
    storage = _RecordingAuthorizationStorage(token_endpoint_auth_method)
    token_requests: list[httpx.Request] = []

    def handle_token_request(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            request=request,
        )

    monkeypatch.setattr(
        oauth,
        "mcp_ssrf_httpx_client_factory",
        lambda **_kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handle_token_request)
        ),
    )
    provider = _provider(storage)

    tokens = asyncio.run(
        provider.complete_authorization_code_exchange("auth-code", "v" * 128)
    )

    assert tokens.access_token == "new-access-token"
    assert storage.tokens == tokens
    assert storage.persisted_client_information == storage.client_info
    assert len(token_requests) == 1
    token_request = token_requests[0]
    expected_body = {
        "grant_type": ["authorization_code"],
        "code": ["auth-code"],
        "redirect_uri": [_REDIRECT_URI],
        "client_id": ["client-id"],
        "code_verifier": ["v" * 128],
        "resource": ["https://mcp.example.com/mcp"],
    }
    if token_endpoint_auth_method == "client_secret_post":
        expected_body["client_secret"] = ["client-id-secret"]
        assert "Authorization" not in token_request.headers
    else:
        expected_credentials = base64.b64encode(b"client-id:client-id-secret").decode()
        assert token_request.headers["Authorization"] == (
            f"Basic {expected_credentials}"
        )
    assert parse_qs(token_request.content.decode()) == expected_body


def test_failed_token_exchange_does_not_persist_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _RecordingAuthorizationStorage()

    def handle_token_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": "invalid_grant", "access_token": "must-not-leak"},
            request=request,
        )

    monkeypatch.setattr(
        oauth,
        "mcp_ssrf_httpx_client_factory",
        lambda **_kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handle_token_request)
        ),
    )

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            _provider(storage).complete_authorization_code_exchange(
                "rejected-code", "v" * 128
            )
        )

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail.endswith("invalid_grant")
    assert "must-not-leak" not in exc_info.value.detail
    assert storage.tokens is None
    assert storage.persisted_client_information is None


def test_invalid_token_response_is_safe_and_not_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = _RecordingAuthorizationStorage()

    def handle_token_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"provider-secret: must-not-leak",
            request=request,
        )

    monkeypatch.setattr(
        oauth,
        "mcp_ssrf_httpx_client_factory",
        lambda **_kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handle_token_request)
        ),
    )

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            _provider(storage).complete_authorization_code_exchange(
                "auth-code", "v" * 128
            )
        )

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY
    assert "invalid token response" in exc_info.value.detail
    assert "provider-secret" not in exc_info.value.detail
    assert storage.tokens is None
    assert storage.persisted_client_information is None


@pytest.mark.parametrize(
    ("failure", "expected_code", "expected_detail"),
    [
        (
            SSRFException("blocked endpoint"),
            OnyxErrorCode.INVALID_INPUT,
            "not allowed",
        ),
        (
            httpx.ConnectError("provider unavailable"),
            OnyxErrorCode.BAD_GATEWAY,
            "request failed",
        ),
    ],
)
def test_token_exchange_sanitizes_transport_failures_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected_code: OnyxErrorCode,
    expected_detail: str,
) -> None:
    storage = _RecordingAuthorizationStorage()

    def failing_client_factory(**_kwargs: object) -> httpx.AsyncClient:
        if isinstance(failure, SSRFException):
            raise failure

        def handle_request(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(str(failure), request=request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle_request))

    monkeypatch.setattr(
        oauth,
        "mcp_ssrf_httpx_client_factory",
        failing_client_factory,
    )

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            _provider(storage).complete_authorization_code_exchange(
                "auth-code", "v" * 128
            )
        )

    assert exc_info.value.error_code is expected_code
    assert expected_detail in exc_info.value.detail
    assert "provider unavailable" not in exc_info.value.detail
    assert storage.tokens is None


def test_sdk_handoff_raises_the_same_authorization_attempt_it_records() -> None:
    handoffs: list[Any] = []

    async def persist_handoff(request: Any, _context: Any) -> None:
        handoffs.append(request)

    provider = _provider(
        _MemoryTokenStorage(), authorization_request_handler=persist_handoff
    )

    async def run() -> None:
        async with httpx.AsyncClient(
            auth=provider,
            transport=httpx.MockTransport(_authorization_required_response),
        ) as client:
            await client.get("https://mcp.example.com/mcp")

    with pytest.raises(oauth.OAuthAuthorizationRequired) as exc_info:
        asyncio.run(run())

    assert handoffs == [exc_info.value.authorization]
    assert handoffs[0].state
    assert handoffs[0].code_verifier


def test_noninteractive_provider_requires_reconnection() -> None:
    provider = _provider(_MemoryTokenStorage())

    async def run() -> None:
        async with httpx.AsyncClient(
            auth=provider,
            transport=httpx.MockTransport(_authorization_required_response),
        ) as client:
            await client.get("https://mcp.example.com/mcp")

    with pytest.raises(
        oauth.MCPReauthenticationRequired,
        match="Please reconnect to the server through Onyx",
    ):
        asyncio.run(run())
