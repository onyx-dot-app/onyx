"""ensure_fresh_connection: one call per connection, temporary and permanent
errors, and each token endpoint source."""

import threading
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import requests
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration import get_integration_by_id
from onyx.db.integration_connection import get_connection_by_id
from onyx.db.models import Integration, User
from onyx.integrations.connection_models import (
    OAUTH_CLIENT_INFO_KEY,
    OAUTH_METADATA_KEY,
    ConnectionSecret,
    ConnectionState,
    read_connection_secret,
)
from onyx.integrations.connections import (
    ConnectionProblem,
    ensure_fresh_connection,
    resolve_connection,
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
    token_response,
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
                own_integration = get_integration_by_id(integration.id, session)
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
    assert result.code is ConnectionState.NEEDS_RECONNECT
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
        app_type=ExternalAppType.LINEAR,
    )
    user = make_test_user("preset_refresh")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    post = MagicMock(
        return_value=token_response(
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
        MagicMock(return_value=token_response({"error": "invalid_grant"}, 400)),
    ):
        ensure_fresh_connection(connection, integration, db_session)
    assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT


def test_preset_refresh_with_a_bad_expires_in_has_no_expiry(
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
        app_type=ExternalAppType.LINEAR,
    )
    user = make_test_user("preset_bad_expiry")
    connection = add_connection(
        db_session, integration, user.id, _stale_secret(), expires_at=expired()
    )
    post = MagicMock(
        return_value=token_response(
            {"access_token": "linear-new", "token_type": "Bearer", "expires_in": "soon"}
        )
    )
    with patch.object(requests, "post", post):
        ensure_fresh_connection(connection, integration, db_session)
    assert read_connection_secret(connection).access_token == "linear-new"
    assert connection.expires_at is None


def test_mcp_refresh_uses_sdk_request(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    sdk_token_url = "https://mcp-auth.example.test/oauth/token"
    integration = make_integration(
        kind=IntegrationKind.MCP,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.DISCOVERY,
        client_id="dcr-client",
        registration={
            OAUTH_CLIENT_INFO_KEY: {
                "client_id": "dcr-client",
                "redirect_uris": ["https://onyx.example.test/mcp/oauth/callback"],
                "token_endpoint_auth_method": "none",
            },
            OAUTH_METADATA_KEY: {
                "issuer": "https://mcp-auth.example.test",
                "authorization_endpoint": "https://mcp-auth.example.test/authorize",
                "token_endpoint": sdk_token_url,
            },
        },
    )
    user: User = make_test_user("mcp_refresh")
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
