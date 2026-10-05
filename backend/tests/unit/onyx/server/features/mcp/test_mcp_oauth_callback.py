import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthMetadata,
    ProtectedResourceMetadata,
)
from pydantic import AnyUrl
from starlette.requests import Request

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.db.models import MCPServer, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api, oauth_flow
from onyx.server.features.mcp.models import (
    MCPConnectionData,
    MCPOAuthFlowState,
)

_REDIRECT_URI = "https://onyx.example.com/mcp/oauth/callback"
_CODE_VERIFIER = "v" * 128
_STATE = "flow-state"


def _client_information(client_id: str = "client-id") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_secret=f"{client_id}-secret",
        redirect_uris=[_REDIRECT_URI],
        token_endpoint_auth_method="client_secret_post",
    )


def _server(
    provider_mode: MCPOAuthProviderMode = MCPOAuthProviderMode.AUTO_DISCOVERY,
) -> SimpleNamespace:
    known_provider = provider_mode is MCPOAuthProviderMode.KNOWN_PROVIDER
    return SimpleNamespace(
        id=42,
        name="Protected MCP",
        server_url="https://mcp.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=MCPTransport.STREAMABLE_HTTP,
        oauth_provider_mode=provider_mode,
        oauth_authorization_endpoint=(
            "https://accounts.example.com/authorize" if known_provider else None
        ),
        oauth_token_endpoint=(
            "https://accounts.example.com/token" if known_provider else None
        ),
        oauth_scopes_override=["files:read"] if known_provider else None,
        oauth_additional_auth_params=None,
        admin_connection_config_id=100,
    )


def _flow(
    server: SimpleNamespace,
) -> MCPOAuthFlowState:
    return MCPOAuthFlowState(
        server_id=server.id,
        connection_config_id=101,
        return_path="/admin/actions/mcp",
        code_verifier=_CODE_VERIFIER,
        redirect_uri=AnyUrl(_REDIRECT_URI),
        server_snapshot=oauth_flow._snapshot_server_configuration(
            cast(MCPServer, server)
        ),
        connection_headers_fingerprint=(
            oauth_flow.mcp_oauth_connection_headers_fingerprint({})
        ),
        client_information_fingerprint=(
            oauth_flow.mcp_oauth_client_information_fingerprint(
                _client_information(),
            )
        ),
        protected_resource_metadata=(
            ProtectedResourceMetadata(
                resource="https://mcp.example.com/mcp",
                authorization_servers=["https://accounts.example.com"],
            )
            if server.oauth_provider_mode is MCPOAuthProviderMode.AUTO_DISCOVERY
            else None
        ),
        oauth_metadata=(
            OAuthMetadata(
                issuer="https://accounts.example.com",
                authorization_endpoint="https://accounts.example.com/authorize",
                token_endpoint="https://accounts.example.com/token",
            )
            if server.oauth_provider_mode is MCPOAuthProviderMode.AUTO_DISCOVERY
            else None
        ),
        authorization_server_url=(
            "https://accounts.example.com"
            if server.oauth_provider_mode is MCPOAuthProviderMode.AUTO_DISCOVERY
            else None
        ),
        protocol_version="2025-06-18",
        scope="files:read",
    )


def _request(**query: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/mcp/oauth/callback",
            "query_string": urlencode(query).encode(),
            "headers": [],
        }
    )


def _install_callback_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    server: SimpleNamespace,
    flow: MCPOAuthFlowState,
) -> tuple[User, MagicMock, SimpleNamespace, MagicMock]:
    user = cast(User, SimpleNamespace(id=uuid4(), email="user@example.com"))
    db_session = MagicMock()
    user_config = SimpleNamespace(id=101)
    attempt_store = MagicMock()
    attempt_store.consume.return_value = SimpleNamespace(payload=flow)
    monkeypatch.setattr(api, "mcp_oauth_attempt_store", lambda: attempt_store)
    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_args: server)
    monkeypatch.setattr(api, "user_can_access_mcp_server", lambda *_args: True)
    monkeypatch.setattr(api, "get_user_connection_config", lambda *_args: user_config)
    monkeypatch.setattr(
        api,
        "extract_connection_data",
        lambda *_args, **_kwargs: MCPConnectionData(
            headers={},
            client_info=_client_information().model_dump(mode="json"),
        ),
    )
    hot_reload = MagicMock()
    monkeypatch.setattr(api, "_hot_reload_craft_sessions", hot_reload)
    return user, db_session, user_config, hot_reload


def test_auto_discovery_callback_dispatches_claimed_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    flow = _flow(server)
    user, db_session, _, hot_reload = _install_callback_dependencies(
        monkeypatch, server, flow
    )
    complete_flow = AsyncMock()
    monkeypatch.setattr(api, "complete_mcp_oauth_authorization", complete_flow)
    response = asyncio.run(
        api.process_oauth_callback(
            _request(state=_STATE, code="authorization-code"),
            db_session,
            user,
        )
    )

    complete_flow.assert_awaited_once_with(
        flow,
        server,
        _client_information(),
        "authorization-code",
    )
    db_session.commit.assert_called_once()
    hot_reload.assert_called_once_with({user.id}, db_session)
    assert response.success
    assert response.redirect_url == flow.return_path


def test_callback_rejects_server_configuration_changed_after_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    flow = _flow(server)
    server.server_url = "https://replacement.example.com/mcp"
    user, db_session, _, _ = _install_callback_dependencies(monkeypatch, server, flow)
    complete_flow = AsyncMock()
    monkeypatch.setattr(api, "complete_mcp_oauth_authorization", complete_flow)

    with pytest.raises(OnyxError, match="server configuration changed"):
        asyncio.run(
            api.process_oauth_callback(
                _request(state=_STATE, code="authorization-code"),
                db_session,
                user,
            )
        )
    complete_flow.assert_not_awaited()


def test_callback_rejects_replaced_connection_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    flow = _flow(server)
    user, db_session, user_config, _ = _install_callback_dependencies(
        monkeypatch, server, flow
    )
    user_config.id = 999

    with pytest.raises(OnyxError, match="connection changed"):
        asyncio.run(
            api.process_oauth_callback(
                _request(state=_STATE, code="authorization-code"),
                db_session,
                user,
            )
        )


def test_callback_rechecks_server_authorization_before_exchanging_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    flow = _flow(server)
    user, db_session, _, hot_reload = _install_callback_dependencies(
        monkeypatch, server, flow
    )
    monkeypatch.setattr(api, "user_can_access_mcp_server", lambda *_args: False)
    monkeypatch.setattr(api, "can_manage_mcp_server", lambda *_args: False)
    complete_flow = AsyncMock()
    monkeypatch.setattr(api, "complete_mcp_oauth_authorization", complete_flow)

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            api.process_oauth_callback(
                _request(state=_STATE, code="authorization-code"),
                db_session,
                user,
            )
        )

    assert exc_info.value.error_code is OnyxErrorCode.UNAUTHORIZED
    complete_flow.assert_not_awaited()
    db_session.commit.assert_not_called()
    hot_reload.assert_not_called()


def test_callback_allows_server_manager_without_server_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    flow = _flow(server)
    user, db_session, _, _ = _install_callback_dependencies(monkeypatch, server, flow)
    monkeypatch.setattr(api, "user_can_access_mcp_server", lambda *_args: False)
    monkeypatch.setattr(api, "can_manage_mcp_server", lambda *_args: True)
    complete_flow = AsyncMock()
    monkeypatch.setattr(api, "complete_mcp_oauth_authorization", complete_flow)

    asyncio.run(
        api.process_oauth_callback(
            _request(state=_STATE, code="authorization-code"),
            db_session,
            user,
        )
    )

    complete_flow.assert_awaited_once_with(
        flow,
        server,
        _client_information(),
        "authorization-code",
    )


def test_callback_claim_is_bound_to_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = cast(User, SimpleNamespace(id=uuid4(), email="user@example.com"))
    attempt_store = MagicMock()
    attempt_store.consume.side_effect = OnyxError(
        OnyxErrorCode.INVALID_INPUT, "Invalid OAuth state"
    )
    monkeypatch.setattr(api, "mcp_oauth_attempt_store", lambda: attempt_store)

    with pytest.raises(OnyxError, match="Invalid OAuth state"):
        asyncio.run(
            api.process_oauth_callback(
                _request(state="another-users-state", code="authorization-code"),
                MagicMock(),
                user,
            )
        )
    attempt_store.consume.assert_called_once_with(
        owner_id=str(user.id),
        state="another-users-state",
    )


def test_provider_denial_claims_flow_without_exchanging_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    flow = _flow(server)
    user, db_session, _, _ = _install_callback_dependencies(monkeypatch, server, flow)
    complete_flow = AsyncMock()
    monkeypatch.setattr(api, "complete_mcp_oauth_authorization", complete_flow)

    with pytest.raises(OnyxError, match="denied or failed"):
        asyncio.run(
            api.process_oauth_callback(
                _request(state=_STATE, error="access_denied"),
                db_session,
                user,
            )
        )
    complete_flow.assert_not_awaited()
    cast(MagicMock, api.mcp_oauth_attempt_store()).consume.assert_called_once_with(
        owner_id=str(user.id),
        state=_STATE,
    )


@pytest.mark.parametrize("provider_mode", list(MCPOAuthProviderMode))
def test_callback_rejects_a_stale_client_registration(
    monkeypatch: pytest.MonkeyPatch,
    provider_mode: MCPOAuthProviderMode,
) -> None:
    server = _server(provider_mode)
    flow = _flow(server)
    user, db_session, _, hot_reload = _install_callback_dependencies(
        monkeypatch, server, flow
    )
    monkeypatch.setattr(
        api,
        "extract_connection_data",
        lambda *_args, **_kwargs: MCPConnectionData(
            headers={},
            client_info=_client_information("replacement-client").model_dump(
                mode="json"
            ),
        ),
    )
    complete_flow = AsyncMock()
    monkeypatch.setattr(api, "complete_mcp_oauth_authorization", complete_flow)

    with pytest.raises(OnyxError, match="client registration changed"):
        asyncio.run(
            api.process_oauth_callback(
                _request(state=_STATE, code="authorization-code"),
                db_session,
                user,
            )
        )

    complete_flow.assert_not_awaited()
    db_session.commit.assert_not_called()
    hot_reload.assert_not_called()
