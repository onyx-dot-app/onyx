import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from mcp.shared.auth import OAuthClientInformationFull

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPOAuthProviderMode,
    MCPTransport,
)
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.server.features.mcp.models import (
    MCPConnectionData,
    MCPToolCreateRequest,
    MCPUserOAuthConnectRequest,
)
from onyx.server.features.mcp.oauth import MCPReauthenticationRequired

_TOKEN_URL = "https://accounts.example.com/token"


def _server() -> SimpleNamespace:
    return SimpleNamespace(
        id=42,
        name="Protected MCP",
        server_url="https://mcp.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        transport=MCPTransport.STREAMABLE_HTTP,
        oauth_provider_mode=MCPOAuthProviderMode.AUTO_DISCOVERY,
        oauth_authorization_endpoint=None,
        oauth_token_endpoint=None,
        oauth_scopes_override=None,
        oauth_additional_auth_params=None,
        admin_connection_config=None,
        admin_connection_config_id=100,
    )


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


def test_tool_discovery_reports_reauthentication_as_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    user = cast(User, SimpleNamespace(id=uuid4(), email="user@example.com"))
    credentials = MagicMock()
    credentials.can_authenticate.return_value = True
    credentials.connection_config = SimpleNamespace(id=101)
    credentials.build_headers.return_value = {"Authorization": "Bearer stale"}

    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_args: server)
    monkeypatch.setattr(api, "_ensure_mcp_server_owner_or_admin", lambda *_args: None)
    monkeypatch.setattr(api, "resolve_mcp_credentials", lambda *_args: credentials)
    monkeypatch.setattr(api, "make_oauth_provider", lambda *_args: MagicMock())
    monkeypatch.setattr(
        api,
        "discover_mcp_tools",
        MagicMock(side_effect=MCPReauthenticationRequired()),
    )

    with pytest.raises(OnyxError) as exc_info:
        api._list_mcp_tools_by_id(server.id, MagicMock(), True, user)

    assert exc_info.value.error_code is OnyxErrorCode.UNAUTHENTICATED
    assert exc_info.value.detail == "Please reconnect to the server through Onyx."


def test_user_cannot_start_oauth_for_an_inaccessible_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _server()
    user = cast(User, SimpleNamespace(id=uuid4(), email="user@example.com"))
    create_config = MagicMock()
    start_flow = AsyncMock()
    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_args: server)
    monkeypatch.setattr(api, "user_can_access_mcp_server", lambda *_args: False)
    monkeypatch.setattr(api, "create_connection_config", create_config)
    monkeypatch.setattr(api, "start_auto_discovery_oauth_flow", start_flow)

    with pytest.raises(OnyxError) as exc_info:
        asyncio.run(
            api._connect_oauth(
                _request(server.id),
                MagicMock(),
                is_admin=False,
                user=user,
            )
        )

    assert exc_info.value.error_code is OnyxErrorCode.UNAUTHORIZED
    create_config.assert_not_called()
    start_flow.assert_not_awaited()


@pytest.mark.parametrize(
    ("expires_at", "force_reauthentication", "stored_credentials_usable"),
    [
        (4_000_000_000.0, False, True),
        (4_000_000_000.0, True, True),
        (1.0, False, False),
    ],
    ids=["valid", "forced", "expired"],
)
def test_token_expiry_controls_fast_path_without_dropping_oauth_state(
    monkeypatch: pytest.MonkeyPatch,
    expires_at: float,
    force_reauthentication: bool,
    stored_credentials_usable: bool,
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
        metadata={"token_endpoint": _TOKEN_URL},
    )
    server = _server()
    user = SimpleNamespace(id=uuid4(), email="user@example.com")
    user_config = SimpleNamespace(id=101)
    update_connection_config = MagicMock()
    start_flow = AsyncMock(
        return_value=(
            api.OAuthAlreadyAuthenticated()
            if stored_credentials_usable and not force_reauthentication
            else api.OAuthAuthorizationRedirect("https://accounts.example.com/consent")
        )
    )

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
    monkeypatch.setattr(api, "start_auto_discovery_oauth_flow", start_flow)

    request = _request(server.id, force_reauthentication=force_reauthentication)
    original_request = request.model_copy(deep=True)
    response = asyncio.run(
        api._connect_oauth(
            request,
            MagicMock(),
            is_admin=True,
            user=cast(User, user),
        )
    )

    if stored_credentials_usable and not force_reauthentication:
        assert response.status == "already_authenticated"
        assert response.authorization_url is None
    else:
        assert response.status == "authorization_required"
        assert response.authorization_url == "https://accounts.example.com/consent"
    assert response.redirect_url == "/admin/actions/mcp"
    start_flow_call = start_flow.await_args
    assert start_flow_call is not None
    assert start_flow_call.kwargs["credentials_usable"] is stored_credentials_usable
    assert start_flow_call.kwargs["force_reauthentication"] is force_reauthentication
    updated_data = update_connection_config.call_args.args[2]
    assert updated_data["tokens"] == stored_data["tokens"]
    assert updated_data["token_expires_at"] == stored_data["token_expires_at"]
    assert updated_data["metadata"] == stored_data["metadata"]
    assert request == original_request


@pytest.mark.parametrize("explicit_new_client", [False, True])
def test_server_url_change_invalidates_old_credentials_without_losing_new_client(
    monkeypatch: pytest.MonkeyPatch,
    explicit_new_client: bool,
) -> None:
    client_information = OAuthClientInformationFull(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uris=["https://onyx.example.com/mcp/oauth/callback"],
    )
    server = _server()
    server.admin_connection_config = SimpleNamespace(id=100)
    user = cast(User, SimpleNamespace(id=uuid4(), email="admin@example.com"))
    request = MCPToolCreateRequest(
        name=server.name,
        server_url="https://replacement.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        oauth_client_id=("replacement-client" if explicit_new_client else "client-id"),
        oauth_client_secret=(
            "replacement-secret" if explicit_new_client else "client-secret"
        ),
        oauth_client_id_changed=explicit_new_client,
        oauth_client_secret_changed=explicit_new_client,
        transport=MCPTransport.STREAMABLE_HTTP,
        existing_server_id=server.id,
    )
    delete_user_configs = MagicMock()
    delete_admin_config = MagicMock()
    hot_reload = MagicMock()
    persisted_admin_configs: list[MCPConnectionData] = []
    original_request = request.model_copy(deep=True)

    def update_server(*_args: object, **kwargs: object) -> SimpleNamespace:
        for field in (
            "server_url",
            "auth_type",
            "auth_performer",
            "oauth_provider_mode",
            "oauth_authorization_endpoint",
            "oauth_token_endpoint",
            "oauth_scopes_override",
            "oauth_additional_auth_params",
            "transport",
        ):
            if field in kwargs:
                setattr(server, field, kwargs[field])
        return server

    monkeypatch.setattr(api, "_validate_mcp_server_url", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api, "get_mcp_server_by_id", lambda *_args: server)
    monkeypatch.setattr(api, "_ensure_mcp_server_owner_or_admin", lambda *_args: None)
    monkeypatch.setattr(
        api,
        "extract_connection_data",
        lambda *_args, **_kwargs: MCPConnectionData(
            headers={}, client_info=client_information.model_dump(mode="json")
        ),
    )
    monkeypatch.setattr(api, "get_mcp_auth_template", lambda *_args: None)
    monkeypatch.setattr(api, "get_user_connection_config", lambda *_args: None)
    monkeypatch.setattr(
        api, "affected_user_ids_for_mcp_server", lambda *_args: {user.id}
    )
    monkeypatch.setattr(
        api,
        "delete_all_user_connection_configs_for_server_no_commit",
        delete_user_configs,
    )
    monkeypatch.setattr(api, "delete_connection_config", delete_admin_config)
    monkeypatch.setattr(api, "update_mcp_server__no_commit", update_server)

    def persist_admin_config(
        _server: object, config_data: MCPConnectionData, _db: object
    ) -> int:
        persisted_admin_configs.append(config_data)
        return 200

    monkeypatch.setattr(api, "_persist_admin_connection_config", persist_admin_config)
    monkeypatch.setattr(api, "_hot_reload_craft_sessions", hot_reload)
    db_session = MagicMock()

    api._upsert_mcp_server(request, db_session, user)

    delete_user_configs.assert_called_once_with(server.id, db_session)
    delete_admin_config.assert_called_once_with(100, db_session)
    hot_reload.assert_called_once_with({user.id}, db_session)
    assert request == original_request
    assert len(persisted_admin_configs) == 1
    persisted_client = persisted_admin_configs[0].get("client_info")
    if explicit_new_client:
        assert persisted_client is not None
        assert persisted_client["client_id"] == "replacement-client"
        assert persisted_client["client_secret"] == "replacement-secret"
    else:
        assert persisted_client is None
