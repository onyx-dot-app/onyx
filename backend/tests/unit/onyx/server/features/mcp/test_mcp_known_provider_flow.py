import asyncio
import base64
import hashlib
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.shared.auth import OAuthClientInformationFull

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.db.models import MCPServer
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import oauth, oauth_flow
from onyx.server.features.mcp.models import MCPOAuthFlowState

_AUTHORIZATION_URL = "https://accounts.example.com/authorize"
_TOKEN_URL = "https://accounts.example.com/token"
_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"
_CODE_VERIFIER = "v" * 128


def _client_information() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uris=[_REDIRECT_URI],
        token_endpoint_auth_method="client_secret_post",
    )


def _server() -> MCPServer:
    return cast(
        MCPServer,
        SimpleNamespace(
            id=42,
            name="Protected MCP",
            server_url="https://mcp.example.com/mcp",
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            oauth_provider_mode=MCPOAuthProviderMode.KNOWN_PROVIDER,
            oauth_authorization_endpoint=_AUTHORIZATION_URL,
            oauth_token_endpoint=_TOKEN_URL,
            oauth_scopes_override=["files:read"],
            oauth_additional_auth_params=None,
            admin_connection_config_id=100,
        ),
    )


def _flow() -> MCPOAuthFlowState:
    server = _server()
    return MCPOAuthFlowState(
        server_id=server.id,
        connection_config_id=101,
        return_path="/admin/actions/mcp",
        code_verifier=_CODE_VERIFIER,
        redirect_uri=_REDIRECT_URI,
        server_snapshot=oauth_flow._snapshot_server_configuration(server),
        connection_headers_fingerprint=(
            oauth_flow.mcp_oauth_connection_headers_fingerprint({})
        ),
        client_information_fingerprint=(
            oauth_flow.mcp_oauth_client_information_fingerprint(
                _client_information(),
            )
        ),
        resource=server.server_url,
    )


def test_start_persists_the_exact_authorization_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    server.oauth_additional_auth_params = {"prompt": "consent"}
    attempt_store = MagicMock()
    monkeypatch.setattr(oauth_flow, "mcp_oauth_attempt_store", lambda: attempt_store)

    result = oauth_flow.start_known_provider_oauth_flow(
        mcp_server=server,
        user_id="user-1",
        connection_config_id=101,
        return_path="/admin/actions/mcp",
        connection_headers={"X-Gateway-Tenant": "tenant-1"},
        client_information=_client_information(),
        include_resource_param=True,
    )

    query = parse_qs(urlparse(result.url).query)
    attempt_store.store.assert_called_once()
    store_call = attempt_store.store.call_args
    stored_flow = store_call.kwargs["payload"]
    assert store_call.kwargs["owner_id"] == "user-1"
    assert query["state"] == [store_call.kwargs["state"]]
    assert query["resource"] == [server.server_url]
    assert query["scope"] == ["files:read"]
    assert query["prompt"] == ["consent"]
    assert stored_flow.client_information_fingerprint == (
        oauth_flow.mcp_oauth_client_information_fingerprint(
            _client_information(),
        )
    )
    assert stored_flow.code_verifier
    expected_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(stored_flow.code_verifier.encode()).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    assert query["code_challenge"] == [expected_challenge]
    assert query["code_challenge_method"] == ["S256"]
    assert str(stored_flow.resource) == server.server_url
    assert stored_flow.server_snapshot.provider_mode is (
        MCPOAuthProviderMode.KNOWN_PROVIDER
    )


def test_start_rejects_invalid_known_provider_configuration() -> None:
    missing_endpoint_server = _server()
    missing_endpoint_server.oauth_token_endpoint = None
    with pytest.raises(OnyxError, match="oauth_token_endpoint"):
        oauth_flow.start_known_provider_oauth_flow(
            mcp_server=missing_endpoint_server,
            user_id="user-1",
            connection_config_id=101,
            return_path="/admin/actions/mcp",
            connection_headers={},
            client_information=_client_information(),
            include_resource_param=True,
        )

    missing_client_id = _client_information().model_copy(update={"client_id": ""})
    with pytest.raises(OnyxError, match="client_id"):
        oauth_flow.start_known_provider_oauth_flow(
            mcp_server=_server(),
            user_id="user-1",
            connection_config_id=101,
            return_path="/admin/actions/mcp",
            connection_headers={},
            client_information=missing_client_id,
            include_resource_param=True,
        )

    unsafe_legacy_server = _server()
    unsafe_legacy_server.oauth_additional_auth_params = {"state": "overridden"}
    with pytest.raises(OnyxError, match="cannot override: state"):
        oauth_flow.start_known_provider_oauth_flow(
            mcp_server=unsafe_legacy_server,
            user_id="user-1",
            connection_config_id=101,
            return_path="/admin/actions/mcp",
            connection_headers={},
            client_information=_client_information(),
            include_resource_param=True,
        )


def test_completion_uses_configured_provider_context_and_sdk_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = _flow()
    token_requests: list[httpx.Request] = []

    def handle_token_request(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        return httpx.Response(
            200,
            json={
                "access_token": "known-provider-token",
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
    persist_result = AsyncMock()
    monkeypatch.setattr(
        oauth.OnyxTokenStorage,
        "set_authorization_result",
        persist_result,
    )

    asyncio.run(
        oauth_flow.complete_mcp_oauth_flow(
            flow,
            _server(),
            _client_information(),
            "authorization-code",
        )
    )

    assert len(token_requests) == 1
    token_request = token_requests[0]
    assert str(token_request.url) == _TOKEN_URL
    assert parse_qs(token_request.content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["authorization-code"],
        "redirect_uri": [_REDIRECT_URI],
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "code_verifier": [_CODE_VERIFIER],
        "resource": ["https://mcp.example.com/mcp"],
    }
    persist_result.assert_awaited_once()
    persist_call = persist_result.await_args
    assert persist_call is not None
    persisted_tokens, persisted_client = persist_call.args
    assert persisted_tokens.access_token == "known-provider-token"
    assert persisted_client == _client_information()
