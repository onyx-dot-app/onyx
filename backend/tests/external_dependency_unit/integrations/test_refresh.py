"""ensure_fresh_connection: one call per connection, temporary and permanent
errors, and each token endpoint source."""

import threading
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import requests
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.integration_connection import fetch_integration, get_connection_by_id
from onyx.db.models import ExternalApp, Integration, MCPServer, User
from onyx.integrations.connection_models import (
    ConnectionProblemCode,
    ConnectionSecret,
    read_connection_secret,
)
from onyx.integrations.connections import (
    ConnectionProblem,
    ensure_fresh_connection,
    resolve_connection,
)
from onyx.server.features.mcp.oauth import (
    INTEGRATION_CLIENT_INFO_KEY,
    INTEGRATION_OAUTH_METADATA_KEY,
)
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integrations.conftest import (
    TOKEN_URL,
    FakeTokenEndpoint,
    MakeIntegration,
    add_connection,
    expired,
    far_future,
)


def _manual_integration(make_integration: MakeIntegration) -> Integration:
    return make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
        client_id="client",
        client_secret="secret",
    )


def _stale_secret() -> ConnectionSecret:
    return ConnectionSecret(
        access_token="old-access", refresh_token="old-refresh", token_type="Bearer"
    )


def test_two_concurrent_refreshes_make_one_call(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(make_integration)
    user = make_test_user("concurrent_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.delay_s = 0.5
    tenant_id = CURRENT_TENANT_ID_CONTEXTVAR.get()
    results: list[str | None] = []
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def refresh() -> None:
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            with get_session_with_current_tenant() as session:
                own_connection = get_connection_by_id(session, connection.id)
                own_integration = fetch_integration(session, integration.id)
                assert own_connection is not None and own_integration is not None
                start.wait()
                fresh = ensure_fresh_connection(
                    own_connection, own_integration, session
                )
                results.append(read_connection_secret(fresh).access_token)
        except BaseException as error:
            errors.append(error)
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    threads = [threading.Thread(target=refresh) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors
    assert len(token_endpoint.requests) == 1
    assert results == ["new-access", "new-access"]
    body = parse_qs(token_endpoint.requests[0].content.decode())
    assert body["grant_type"] == ["refresh_token"]
    assert body["refresh_token"] == ["old-refresh"]
    assert body["client_id"] == ["client"]
    assert str(token_endpoint.requests[0].url) == TOKEN_URL

    db_session.refresh(connection)
    secret = read_connection_secret(connection)
    assert secret.refresh_token == "new-refresh"
    assert connection.expires_at is not None and connection.expires_at > expired()


def test_fresh_token_makes_no_call(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(make_integration)
    user = make_test_user("fresh_token")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=far_future()
    )
    ensure_fresh_connection(connection, integration, db_session)
    assert token_endpoint.requests == []


def test_dead_refresh_token_needs_reconnect_and_keeps_row(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(make_integration)
    user = make_test_user("dead_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = 400
    token_endpoint.body = {"error": "invalid_grant"}

    result = resolve_connection(integration, user, db_session)

    assert isinstance(result, ConnectionProblem)
    assert result.code is ConnectionProblemCode.NEEDS_RECONNECT
    assert "invalid_grant" in result.reason
    kept = get_connection_by_id(db_session, connection.id)
    assert kept is not None
    assert kept.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert kept.status_reason == result.reason
    assert read_connection_secret(kept).refresh_token == "old-refresh"

    # A row that needs reconnect is not refreshed again.
    resolve_connection(integration, user, db_session)
    assert len(token_endpoint.requests) == 1


def test_temporary_error_keeps_token(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(make_integration)
    user = make_test_user("temporary_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    token_endpoint.status_code = 503
    token_endpoint.body = {"error": "temporarily_unavailable"}

    ensure_fresh_connection(connection, integration, db_session)

    db_session.refresh(connection)
    assert connection.status is IntegrationConnectionStatus.CONNECTED
    assert read_connection_secret(connection).access_token == "old-access"
    assert len(token_endpoint.requests) == 1


def test_expired_token_without_refresh_token_needs_reconnect(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _manual_integration(make_integration)
    user = make_test_user("no_refresh_token")
    connection = add_connection(
        db_session,
        integration,
        user.id,
        ConnectionSecret(access_token="old"),
        expires_at=expired(),
    )
    ensure_fresh_connection(connection, integration, db_session)
    assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert token_endpoint.requests == []


def _token_response(status: int, body: dict[str, Any]) -> requests.Response:
    response = MagicMock(spec=requests.Response)
    response.status_code = status
    response.json.return_value = body
    return response


def test_preset_refresh_uses_provider(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
) -> None:
    integration = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.PRESET,
        client_id="linear-client",
        client_secret="linear-secret",
    )
    app = ExternalApp(
        name=f"Linear {integration.id}",
        app_type=ExternalAppType.LINEAR,
        upstream_url_patterns=[],
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials={},
        integration_id=integration.id,
    )
    db_session.add(app)
    db_session.commit()
    user = make_test_user("preset_refresh")
    try:
        connection = add_connection(
            db_session, integration, user.id, _stale_secret(), expires_at=expired()
        )
        post = MagicMock(
            return_value=_token_response(
                200,
                {
                    "access_token": "linear-new",
                    "refresh_token": "linear-refresh-2",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        )
        with patch.object(requests, "post", post):
            ensure_fresh_connection(connection, integration, db_session)
        assert post.call_count == 1
        assert post.call_args.kwargs["data"]["client_id"] == "linear-client"
        secret = read_connection_secret(connection)
        assert secret.access_token == "linear-new"
        assert secret.refresh_token == "linear-refresh-2"

        connection.expires_at = expired()
        db_session.commit()
        with patch.object(
            requests,
            "post",
            MagicMock(return_value=_token_response(400, {"error": "invalid_grant"})),
        ):
            ensure_fresh_connection(connection, integration, db_session)
        assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    finally:
        db_session.rollback()
        db_session.execute(delete(ExternalApp).where(ExternalApp.id == app.id))
        db_session.commit()


def test_mcp_refresh_uses_sdk_request(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    sdk_token_url = "https://mcp-auth.example.test/oauth/token"
    integration = make_integration(
        kind=IntegrationKind.MCP_SERVER,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.DISCOVERY,
        client_id="dcr-client",
        registration={
            INTEGRATION_CLIENT_INFO_KEY: {
                "client_id": "dcr-client",
                "redirect_uris": ["https://onyx.example.test/mcp/oauth/callback"],
                "token_endpoint_auth_method": "none",
            },
            INTEGRATION_OAUTH_METADATA_KEY: {
                "issuer": "https://mcp-auth.example.test",
                "authorization_endpoint": "https://mcp-auth.example.test/authorize",
                "token_endpoint": sdk_token_url,
            },
        },
    )
    user: User = make_test_user("mcp_refresh")
    server = MCPServer(
        owner=user.email,
        name=f"mcp-{integration.id}",
        server_url="https://mcp.example.test/mcp",
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        integration_id=integration.id,
    )
    db_session.add(server)
    db_session.commit()
    try:
        connection = add_connection(
            db_session, integration, user.id, _stale_secret(), expires_at=expired()
        )
        ensure_fresh_connection(connection, integration, db_session)

        assert len(token_endpoint.requests) == 1
        request = token_endpoint.requests[0]
        assert str(request.url) == sdk_token_url
        body = parse_qs(request.content.decode())
        assert body["refresh_token"] == ["old-refresh"]
        assert body["client_id"] == ["dcr-client"]
        assert read_connection_secret(connection).access_token == "new-access"
    finally:
        db_session.rollback()
        db_session.execute(delete(MCPServer).where(MCPServer.id == server.id))
        db_session.commit()
