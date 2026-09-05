from types import SimpleNamespace
from typing import cast

import pytest
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.db.models import MCPServer
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import oauth_flow
from onyx.server.features.mcp.models import MCPOAuthFlowState
from tests.unit.fakes import FakeCache

_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"
_CODE_VERIFIER = "v" * 128
_STATE = "s" * 32


def _server() -> MCPServer:
    return cast(
        MCPServer,
        SimpleNamespace(
            id=42,
            server_url="https://mcp.example.com/mcp",
            auth_type=MCPAuthenticationType.OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
            oauth_authorization_endpoint=None,
            oauth_token_endpoint=None,
            oauth_scopes_override=None,
            oauth_additional_auth_params=None,
        ),
    )


def _flow() -> MCPOAuthFlowState:
    server = _server()
    return MCPOAuthFlowState(
        server_id=server.id,
        connection_config_id=101,
        return_path="/admin/actions/mcp",
        code_verifier=_CODE_VERIFIER,
        redirect_uri=AnyUrl(_REDIRECT_URI),
        server_snapshot=oauth_flow._snapshot_server_configuration(server),
        connection_headers_fingerprint=(
            oauth_flow.mcp_oauth_connection_headers_fingerprint({})
        ),
        client_information_fingerprint=(
            oauth_flow.mcp_oauth_client_information_fingerprint(
                OAuthClientInformationFull(
                    client_id="client-id",
                    client_secret="sensitive-client-secret",
                    redirect_uris=[_REDIRECT_URI],
                )
            )
        ),
    )


def test_mcp_attempt_store_round_trips_server_side_pkce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    monkeypatch.setattr(oauth_flow, "get_cache_backend", lambda: cache)

    stored = oauth_flow.mcp_oauth_attempt_store().store(
        owner_id="user-1",
        state=_STATE,
        payload=_flow(),
    )

    assert set(cache.expiries.values()) == {oauth_flow.MCP_OAUTH_FLOW_TTL_SECONDS}
    assert b"sensitive-client-secret" not in next(iter(cache.store.values()))
    consumed = oauth_flow.mcp_oauth_attempt_store().consume(
        owner_id="user-1",
        state=_STATE,
    )
    assert consumed == stored
    assert consumed.payload.code_verifier == _CODE_VERIFIER


def test_flow_rejects_changed_server_or_routing_configuration() -> None:
    server = _server()
    flow = _flow()

    oauth_flow.validate_mcp_oauth_flow_configuration(flow, server, {})
    oauth_flow.validate_mcp_oauth_flow_configuration(
        flow,
        server,
        {"Authorization": "Bearer token-written-after-flow-started"},
    )

    changed_server = _server()
    changed_server.server_url = "https://replacement.example.com/mcp"
    with pytest.raises(OnyxError, match="server configuration changed"):
        oauth_flow.validate_mcp_oauth_flow_configuration(flow, changed_server, {})
    with pytest.raises(OnyxError, match="headers changed"):
        oauth_flow.validate_mcp_oauth_flow_configuration(
            flow, server, {"X-Gateway-Tenant": "other-tenant"}
        )
