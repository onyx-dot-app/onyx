"""OAuth MCP grants that can never refresh must read as unauthenticated (ext-dep):
`user_can_authenticate` semantics, Craft config exclusion, and the persisted token
discard on an `invalid_grant` refresh response, against a real DB."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from mcp.shared.auth import OAuthToken
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import (
    create_connection_config,
    create_mcp_server__no_commit,
    get_user_connection_config,
    update_mcp_server__no_commit,
    upsert_user_connection_config,
)
from onyx.db.models import MCPServer, User
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.sandbox.util.mcp_config import (
    resolve_craft_mcp_servers,
)
from onyx.server.features.mcp import api
from onyx.server.features.mcp.api import save_user_credentials
from onyx.server.features.mcp.credentials import (
    extract_connection_data,
    user_can_authenticate,
    user_connection_status,
)
from onyx.server.features.mcp.models import (
    MCPConnectionData,
    MCPConnectionStatus,
    MCPUserCredentialsRequest,
    MCPUserOAuthConnectRequest,
)
from onyx.server.features.mcp.oauth import (
    OnyxTokenStorage,
    make_oauth_provider,
)
from tests.external_dependency_unit.conftest import create_test_user


def _make_oauth_server(db_session: Session, *, owner_email: str) -> MCPServer:
    server = create_mcp_server__no_commit(
        owner_email=owner_email,
        name=f"oauth-{uuid4().hex[:8]}",
        description=None,
        server_url=f"https://mcp-{uuid4().hex[:8]}.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        db_session=db_session,
        is_public=True,
    )
    update_mcp_server__no_commit(
        server_id=server.id, db_session=db_session, available_in_craft=True
    )
    db_session.commit()
    return server


def _store_grant(
    db_session: Session,
    server: MCPServer,
    user: User,
    *,
    expires_at: float,
    refresh_token: str | None,
) -> int:
    tokens: dict[str, Any] = {
        "access_token": "access-token",
        "token_type": "Bearer",
        "refresh_token": refresh_token,
    }
    config_data: MCPConnectionData = {
        "headers": {"Authorization": "Bearer access-token"},
        "tokens": tokens,
        "token_expires_at": expires_at,
    }
    config = upsert_user_connection_config(
        server.id, user.email, config_data, db_session
    )
    db_session.commit()
    return config.id


def test_expired_token_with_refresh_token_is_authenticated(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "oauth_refreshable")
    server = _make_oauth_server(db_session, owner_email=user.email)
    _store_grant(
        db_session,
        server,
        user,
        expires_at=time.time() - 60,
        refresh_token="refresh-token",
    )
    assert user_can_authenticate(server, user, db_session)
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.CONNECTED
    )


def test_dead_grant_is_not_authenticated_and_excluded_from_craft(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "oauth_dead")
    server = _make_oauth_server(db_session, owner_email=user.email)

    def craft_server_ids() -> list[int]:
        return [r.server_id for r in resolve_craft_mcp_servers(db_session, user)]

    # Positive control: a live grant authenticates and reaches Craft configs,
    # so the exclusion below can't pass vacuously.
    _store_grant(
        db_session, server, user, expires_at=time.time() + 3600, refresh_token=None
    )
    assert user_can_authenticate(server, user, db_session)
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.CONNECTED
    )
    assert server.id in craft_server_ids()

    _store_grant(
        db_session, server, user, expires_at=time.time() - 60, refresh_token=None
    )
    assert not user_can_authenticate(server, user, db_session)
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.REAUTH_REQUIRED
    )
    assert server.id not in craft_server_ids()


def _invalid_grant_response() -> httpx.Response:
    return httpx.Response(
        status_code=400,
        json={"error": "invalid_grant"},
        request=httpx.Request("POST", "https://oauth2.example.com/token"),
    )


def test_invalid_grant_refresh_discards_persisted_tokens(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "oauth_revoked")
    server = _make_oauth_server(db_session, owner_email=user.email)
    config_id = _store_grant(
        db_session,
        server,
        user,
        expires_at=time.time() - 60,
        refresh_token="revoked-refresh-token",
    )

    provider = make_oauth_provider(server, config_id, None)

    # A temporary provider failure must preserve the grant and connection state.
    provider.redeemed_refresh_token = "revoked-refresh-token"
    assert not asyncio.run(
        provider._handle_refresh_response(
            httpx.Response(
                503,
                json={"error": "temporarily_unavailable"},
                request=httpx.Request("POST", "https://oauth2.example.com/token"),
            )
        )
    )
    db_session.expire_all()
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.CONNECTED
    )

    # A stale attempt (its refresh token was already rotated away by a
    # concurrent refresh or reconnect) must not wipe the stored grant.
    provider.redeemed_refresh_token = "rotated-away-refresh-token"
    assert not asyncio.run(provider._handle_refresh_response(_invalid_grant_response()))
    db_session.expire_all()
    config = get_user_connection_config(server.id, user.email, db_session)
    assert config is not None
    assert "tokens" in extract_connection_data(config, apply_mask=False)

    # The attempt that redeemed the stored refresh token discards the grant.
    provider.redeemed_refresh_token = "revoked-refresh-token"
    assert not asyncio.run(provider._handle_refresh_response(_invalid_grant_response()))
    db_session.expire_all()
    config = get_user_connection_config(server.id, user.email, db_session)
    assert config is not None
    config_value = extract_connection_data(config, apply_mask=False)
    assert config_value["reauth_required"] is True
    assert "tokens" not in config_value
    assert "token_expires_at" not in config_value
    assert "Authorization" not in config_value.get("headers", {})
    assert not user_can_authenticate(server, user, db_session)
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.REAUTH_REQUIRED
    )


def test_oauth_setup_is_not_connected_before_first_grant(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "oauth_first_connection")
    server = _make_oauth_server(db_session, owner_email=user.email)
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.NOT_CONNECTED
    )
    upsert_user_connection_config(server.id, user.email, {"headers": {}}, db_session)
    db_session.commit()
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.NOT_CONNECTED
    )


def test_successful_reauthorization_clears_reauth_status(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "oauth_reconnect")
    server = _make_oauth_server(db_session, owner_email=user.email)
    config = upsert_user_connection_config(
        server.id, user.email, {"headers": {}, "reauth_required": True}, db_session
    )
    db_session.commit()
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.REAUTH_REQUIRED
    )
    asyncio.run(
        OnyxTokenStorage(config.id).set_tokens(
            OAuthToken(access_token="replacement", token_type="Bearer")
        )
    )
    db_session.expire_all()
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.CONNECTED
    )


def test_header_save_preserves_oauth_reauth_required(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "oauth_header_reconnect")
    server = _make_oauth_server(db_session, owner_email=user.email)
    admin_config = create_connection_config(
        config_data={"headers": {}, "header_template": {"X-Workspace": "{workspace}"}},
        db_session=db_session,
        user_email=user.email,
    )
    server.admin_connection_config_id = admin_config.id
    db_session.commit()
    upsert_user_connection_config(
        server.id, user.email, {"headers": {}, "reauth_required": True}, db_session
    )
    db_session.commit()
    response = save_user_credentials(
        MCPUserCredentialsRequest(
            server_id=server.id,
            credentials={"workspace": "new-workspace"},
            transport="streamable_http",
        ),
        db_session,
        user,
    )
    assert response.authenticated is False
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.REAUTH_REQUIRED
    )


@pytest.mark.parametrize("initialization_fails", [False, True])
def test_oauth_reconnect_preserves_status_until_authorization_succeeds(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    initialization_fails: bool,
) -> None:
    user = create_test_user(db_session, "oauth_pending_reconnect")
    server = _make_oauth_server(db_session, owner_email=user.email)
    admin_config = create_connection_config(
        config_data={"headers": {}},
        db_session=db_session,
        user_email="",
    )
    server.admin_connection_config_id = admin_config.id
    upsert_user_connection_config(
        server.id, user.email, {"headers": {}, "reauth_required": True}, db_session
    )
    db_session.commit()
    start_flow = AsyncMock(
        return_value=api.OAuthAuthorizationRedirect(
            "https://oauth.example.com/authorize"
        ),
        side_effect=RuntimeError("Provider unavailable")
        if initialization_fails
        else None,
    )
    monkeypatch.setattr(api, "start_auto_discovery_oauth_flow", start_flow)
    request = MCPUserOAuthConnectRequest(
        server_id=server.id,
        return_path="/app",
        include_resource_param=True,
        force_reauthentication=True,
    )
    if initialization_fails:
        with pytest.raises(OnyxError, match="Failed to initialize OAuth client"):
            asyncio.run(api._connect_oauth(request, db_session, False, user))
    else:
        response = asyncio.run(api._connect_oauth(request, db_session, False, user))
        assert response.status == "authorization_required"
        # A user who cancels at the provider never completes the callback.
    db_session.expire_all()
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.REAUTH_REQUIRED
    )


def test_first_header_save_does_not_inherit_admin_reauth_status(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    user = create_test_user(db_session, "oauth_header_first_connection")
    server = _make_oauth_server(db_session, owner_email=user.email)
    admin_config = create_connection_config(
        config_data={
            "headers": {},
            "header_template": {"X-Workspace": "{workspace}"},
            "client_info": {"client_id": "shared-client"},
            "reauth_required": True,
        },
        db_session=db_session,
        user_email="",
    )
    server.admin_connection_config_id = admin_config.id
    db_session.commit()
    response = save_user_credentials(
        MCPUserCredentialsRequest(
            server_id=server.id,
            credentials={"workspace": "new-workspace"},
            transport="streamable_http",
        ),
        db_session,
        user,
    )
    assert response.authenticated is False
    assert (
        user_connection_status(server, user, db_session)
        == MCPConnectionStatus.NOT_CONNECTED
    )
    config = get_user_connection_config(server.id, user.email, db_session)
    saved_data = extract_connection_data(config, apply_mask=False)
    assert saved_data.get("client_info") == {"client_id": "shared-client"}
    assert not saved_data.get("reauth_required")
