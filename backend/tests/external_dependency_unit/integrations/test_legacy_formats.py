"""Connections and OAuth clients that the integration tables migration copied
in an old format (legacy_format). Rows are seeded as the migration writes
them: the old dict through the encrypted column, or plain JSON bytes for
tool headers."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

from mcp.shared.auth import OAuthToken
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationLegacyFormat,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration import get_mcp_server_for_integration
from onyx.db.integration_connection import (
    get_connection,
    get_oauth_client,
    mark_connection_needs_reconnect__no_commit,
    update_connection_secret__no_commit,
)
from onyx.db.models import (
    Integration,
    IntegrationConnection,
)
from onyx.integrations.connection_models import (
    OAUTH_CLIENT_INFO_KEY,
    OAUTH_METADATA_KEY,
    SIGN_IN_EXPIRED_REASON,
    SIGN_IN_REJECTED_REASON,
    ConnectionState,
    read_connection,
    read_connection_secret,
    read_oauth_client,
)
from onyx.integrations.connections import (
    _refresh_connection,
    ensure_fresh_connection,
    integration_status,
    mark_sign_in_settings_changed,
    oauth_client_configured,
    preset_host_values,
    render_headers,
    resolve_connection,
)
from onyx.server.features.mcp.oauth import (
    IntegrationTokenStorage,
    integration_mcp_server_connection,
    make_integration_oauth_provider,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    make_app_integration,
    make_mcp_integration,
)
from tests.external_dependency_unit.integrations.conftest import (
    TOKEN_URL,
    FakeTokenEndpoint,
    expect_problem,
    expect_resolved,
    new_oauth_client,
)

_MCP_TOKEN_URL = "https://mcp-auth.example.test/oauth/token"


def _seed(
    db_session: Session,
    integration: Integration,
    user_id: UUID | None,
    legacy_format: IntegrationLegacyFormat,
    old_secret: dict[str, Any],
    *,
    granted_scopes: list[str] | None = None,
) -> IntegrationConnection:
    connection = IntegrationConnection(
        integration_id=integration.id,
        user_id=user_id,
        secret=old_secret,
        legacy_format=legacy_format.value,
        granted_scopes=granted_scopes,
        status=IntegrationConnectionStatus.CONNECTED,
    )
    db_session.add(connection)
    db_session.commit()
    return connection


def _tag_oauth_client(
    db_session: Session,
    integration: Integration,
    legacy_format: IntegrationLegacyFormat,
) -> None:
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    oauth_client.legacy_format = legacy_format.value
    db_session.commit()


def _unix(delta: timedelta) -> float:
    return (datetime.now(timezone.utc) + delta).timestamp()


def test_mcp_config_shared_api_key(
    db_session: Session,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {"Authorization": "Bearer sk-1", "X-Static": "v{1}"},
            "header_template": {"Authorization": "Bearer {api_key}"},
            "api_token": "sk-1",
            "header_substitutions": {},
        },
    )

    secret = expect_resolved(resolve_connection(integration, None, db_session)).secret
    assert render_headers(integration.header_template, secret) == {
        "Authorization": "Bearer sk-1",
        "X-Static": "v{1}",
    }


def test_mcp_config_individual_api_key_and_reauth(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    # A per-user API key server kept its template in the admin headers.
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.MCP_CONFIG,
        {"headers": {"Authorization": "Bearer {api_key}", "X-User": "{user_email}"}},
    )
    user = make_test_user("legacy_mcp_key")
    rejected_user = make_test_user("legacy_mcp_rejected")
    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {"Authorization": "Bearer user-key"},
            "header_substitutions": {"api_key": "user-key"},
        },
    )
    _seed(
        db_session,
        integration,
        rejected_user.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {"Authorization": "Bearer old-key"},
            "header_substitutions": {"api_key": "old-key"},
            "reauth_required": True,
        },
    )

    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret
    assert render_headers(
        integration.header_template, secret, extra_values={"user_email": user.email}
    ) == {"Authorization": "Bearer user-key", "X-User": user.email}
    assert (
        integration_status(integration, user, db_session).state
        is ConnectionState.CONNECTED
    )

    problem = expect_problem(resolve_connection(integration, rejected_user, db_session))
    assert problem.code is ConnectionState.NEEDS_RECONNECT
    assert problem.reason == SIGN_IN_REJECTED_REASON
    status = integration_status(integration, rejected_user, db_session)
    assert status.state is ConnectionState.NEEDS_RECONNECT
    assert status.reason == SIGN_IN_REJECTED_REASON

    # A status change alone keeps the old format.
    row = get_connection(db_session, integration.id, rejected_user.id)
    assert row is not None
    mark_connection_needs_reconnect__no_commit(db_session, row, "Key expired")
    db_session.commit()
    db_session.refresh(row)
    assert row.legacy_format == IntegrationLegacyFormat.MCP_CONFIG.value
    assert read_connection_secret(row).fields == {"api_key": "old-key"}


def _mcp_oauth_integration(
    db_session: Session,
) -> Integration:
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.DISCOVERY,
            registration={
                "headers": {},
                "client_info": {
                    "client_id": "dcr-client",
                    "redirect_uris": ["https://onyx.example.test/mcp/oauth/callback"],
                    "token_endpoint_auth_method": "none",
                },
                "metadata": {
                    "issuer": "https://mcp-auth.example.test",
                    "authorization_endpoint": "https://mcp-auth.example.test/authorize",
                    "token_endpoint": _MCP_TOKEN_URL,
                },
            },
        ),
    )
    _tag_oauth_client(db_session, integration, IntegrationLegacyFormat.MCP_CONFIG)
    return integration


def _mcp_oauth_user_secret(expires_at: float) -> dict[str, Any]:
    return {
        "headers": {"Authorization": "Bearer a1", "X-Route": "eu"},
        "tokens": {
            "access_token": "a1",
            "refresh_token": "r1",
            "token_type": "Bearer",
            "scope": "read write",
            "expires_in": 3600,
        },
        "token_expires_at": expires_at,
    }


def test_mcp_config_token_storage_loads_and_saves_new_format(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration = _mcp_oauth_integration(db_session)
    user = make_test_user("legacy_mcp_storage")
    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        _mcp_oauth_user_secret(_unix(timedelta(hours=1))),
    )
    storage = IntegrationTokenStorage(integration.id, user.id)

    client = asyncio.run(storage.get_client_info())
    assert client is not None and client.client_id == "dcr-client"
    tokens = asyncio.run(storage.get_tokens())
    assert tokens is not None
    assert (tokens.access_token, tokens.refresh_token) == ("a1", "r1")
    assert tokens.scope == "read write"

    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret
    # The stale token copy in the old headers is dropped.
    assert render_headers(integration.header_template, secret) == {"X-Route": "eu"}

    asyncio.run(storage.set_tokens(OAuthToken(access_token="a2", expires_in=60)))
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    db_session.refresh(connection)
    assert connection.legacy_format is None
    assert connection.granted_scopes == ["read", "write"]
    assert connection.secret.get_value(apply_mask=False) == {
        "access_token": "a2",
        "refresh_token": "r1",
        "token_type": "Bearer",
        "fields": {},
        "headers": {"X-Route": "eu"},
    }


def test_mcp_config_refresh_writes_new_format(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _mcp_oauth_integration(db_session)
    user = make_test_user("legacy_mcp_refresh")
    connection = _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        _mcp_oauth_user_secret(_unix(-timedelta(minutes=5))),
    )
    assert connection.expires_at is None

    ensure_fresh_connection(connection, integration, db_session)

    assert len(token_endpoint.requests) == 1
    request = token_endpoint.requests[0]
    assert str(request.url) == _MCP_TOKEN_URL
    assert parse_qs(request.content.decode())["refresh_token"] == ["r1"]
    db_session.refresh(connection)
    assert connection.legacy_format is None
    assert connection.expires_at is not None
    assert connection.granted_scopes == ["read", "write"]
    secret = read_connection_secret(connection)
    assert (secret.access_token, secret.refresh_token) == (
        "new-access",
        "new-refresh",
    )
    assert secret.headers == {"X-Route": "eu"}


def test_mcp_refresh_redeems_the_captured_grant_not_a_newer_one(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration = _mcp_oauth_integration(db_session)
    user = make_test_user("legacy_mcp_refresh_superseded")
    connection = _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        _mcp_oauth_user_secret(_unix(-timedelta(minutes=5))),
    )
    captured = read_connection(connection)
    update_connection_secret__no_commit(
        db_session,
        connection,
        secret={"access_token": "a2", "refresh_token": "r2", "token_type": "Bearer"},
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        granted_scopes=["read"],
    )
    db_session.commit()

    _refresh_connection(connection, captured, integration, db_session)

    assert len(token_endpoint.requests) == 1
    request = token_endpoint.requests[0]
    assert parse_qs(request.content.decode())["refresh_token"] == ["r1"]
    db_session.refresh(connection)
    secret = read_connection_secret(connection)
    assert (secret.access_token, secret.refresh_token) == ("a2", "r2")


def test_mcp_new_authorization_without_scope_keeps_no_old_scopes(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration = _mcp_oauth_integration(db_session)
    user = make_test_user("legacy_mcp_new_auth_scopes")
    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        _mcp_oauth_user_secret(_unix(timedelta(hours=1))),
    )
    storage = IntegrationTokenStorage(integration.id, user.id)
    client = asyncio.run(storage.get_client_info())
    assert client is not None

    asyncio.run(
        storage.set_authorization_result(
            OAuthToken(access_token="a2", refresh_token="r2", expires_in=60), client
        )
    )
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    db_session.refresh(connection)
    assert connection.granted_scopes is None


def test_mcp_config_registration_saves_new_format(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration = _mcp_oauth_integration(db_session)
    user = make_test_user("legacy_mcp_registration")
    storage = IntegrationTokenStorage(integration.id, user.id)
    server = get_mcp_server_for_integration(integration.id, db_session)
    assert server is not None
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    provider = make_integration_oauth_provider(
        integration_mcp_server_connection(server, integration, oauth_client),
        storage,
    )
    asyncio.run(storage.get_tokens())
    assert provider.context.oauth_metadata is not None
    # A token save with the metadata rewrites the client in the new format.
    asyncio.run(storage.set_tokens(OAuthToken(access_token="a1")))

    db_session.refresh(oauth_client)
    assert oauth_client.legacy_format is None
    assert oauth_client.client_id is not None
    assert oauth_client.client_id.get_value(apply_mask=False) == "dcr-client"
    assert oauth_client.registration is not None
    registration = oauth_client.registration.get_value(apply_mask=False)
    assert registration[OAUTH_CLIENT_INFO_KEY]["client_id"] == "dcr-client"
    assert registration[OAUTH_METADATA_KEY]["token_endpoint"] == _MCP_TOKEN_URL


def test_oauth_user_token_refresh_writes_new_format(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL,
            client_id="client",
            client_secret="secret",
        ),
    )
    user = make_test_user("legacy_oauth_token")
    connection = _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.OAUTH_USER_TOKEN,
        {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "token_type": "Bearer",
            "expires_at": int(_unix(-timedelta(minutes=5))),
            "scope": "repo",
        },
    )

    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret

    assert len(token_endpoint.requests) == 1
    assert str(token_endpoint.requests[0].url) == TOKEN_URL
    assert render_headers(integration.header_template, secret) == {
        "Authorization": "Bearer new-access"
    }
    db_session.refresh(connection)
    assert connection.legacy_format is None
    assert connection.granted_scopes == ["repo"]
    assert connection.secret.get_value(apply_mask=False)["refresh_token"] == (
        "new-refresh"
    )


def test_oauth_user_token_expired_without_refresh_needs_reconnect(
    db_session: Session,
    make_test_user: MakeTestUser,
    token_endpoint: FakeTokenEndpoint,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.MANUAL, client_id="client"
        ),
    )
    user = make_test_user("legacy_oauth_dead")
    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.OAUTH_USER_TOKEN,
        {"access_token": "old", "expires_at": _unix(-timedelta(minutes=5))},
    )

    status = integration_status(integration, user, db_session)
    assert status.state is ConnectionState.NEEDS_RECONNECT
    assert status.reason == SIGN_IN_EXPIRED_REASON
    problem = expect_problem(resolve_connection(integration, user, db_session))
    assert problem.reason == SIGN_IN_EXPIRED_REASON
    assert token_endpoint.requests == []


def test_preset_registration_and_user_token(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
        app_type=ExternalAppType.ZENDESK,
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            registration={
                "client_id": "zd-client",
                "client_secret": "zd-secret",
                "subdomain": "acme",
            },
        ),
    )
    _tag_oauth_client(db_session, integration, IntegrationLegacyFormat.EXTERNAL_APP_ORG)
    user = make_test_user("legacy_preset")
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    credentials = read_oauth_client(oauth_client)
    assert (credentials.client_id, credentials.client_secret) == (
        "zd-client",
        "zd-secret",
    )
    assert preset_host_values(integration, db_session) == {"subdomain": "acme"}
    assert oauth_client_configured(integration, oauth_client)

    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.EXTERNAL_APP_USER,
        {
            "access_token": "zd-access",
            "refresh_token": "zd-refresh",
            "token_type": "Bearer",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
        granted_scopes=["read"],
    )
    connection = get_connection(db_session, integration.id, user.id)
    assert connection is not None
    record = read_connection(connection)
    assert record.expires_at is not None
    assert record.granted_scopes == ["read"]
    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret
    assert render_headers(integration.header_template, secret) == {
        "Authorization": "Bearer zd-access"
    }


def test_individual_custom_app_merges_organization_fields(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Key": "{api_key}", "X-Region": "{region}"},
    )
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.EXTERNAL_APP_ORG,
        {"api_key": "org-key"},
    )
    user = make_test_user("legacy_custom_app")
    other = make_test_user("legacy_custom_app_other")
    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.EXTERNAL_APP_USER,
        {"api_key": "user-key", "region": "eu"},
    )

    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret
    assert render_headers(integration.header_template, secret) == {
        "X-Key": "user-key",
        "X-Region": "eu",
    }
    # The organization values do not fill the template, so a user with no
    # row is not connected.
    problem = expect_problem(resolve_connection(integration, other, db_session))
    assert problem.code is ConnectionState.NOT_CONNECTED
    assert (
        integration_status(integration, other, db_session).state
        is ConnectionState.NOT_CONNECTED
    )


def test_custom_app_user_fields_named_like_token_fields_are_kept(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Scope": "{scope}", "X-Until": "{expires_at}"},
    )
    user = make_test_user("legacy_custom_fields")
    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.EXTERNAL_APP_USER,
        {"scope": "tenant-a", "expires_at": "never"},
    )

    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret
    assert render_headers(integration.header_template, secret) == {
        "X-Scope": "tenant-a",
        "X-Until": "never",
    }


def test_tool_headers_plain_json(
    db_session: Session,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    db_session.execute(
        text(
            "INSERT INTO integration_connection "
            "(integration_id, user_id, secret, legacy_format, status) "
            "VALUES (:integration_id, NULL, convert_to(:headers, 'UTF8'), "
            "'tool_headers', 'connected')"
        ),
        {
            "integration_id": integration.id,
            "headers": json.dumps(
                [
                    {"key": "X-Api-Key", "value": "abc{1}"},
                    {"key": "X-Empty", "value": ""},
                ]
            ),
        },
    )
    db_session.commit()

    secret = expect_resolved(resolve_connection(integration, None, db_session)).secret
    assert render_headers(integration.header_template, secret) == {
        "X-Api-Key": "abc{1}"
    }
    assert (
        integration_status(integration, None, db_session).state
        is ConnectionState.CONNECTED
    )


def test_mcp_config_no_sign_in_keeps_admin_template(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session, auth_mode=IntegrationAuthMode.NONE, auth_method=None
    )
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {},
            "header_template": {"X-Team": "{team}", "X-User": "{user_email}"},
        },
    )
    user = make_test_user("legacy_mcp_none")
    _seed(
        db_session,
        integration,
        user.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {"headers": {"X-Team": "blue"}, "header_substitutions": {"team": "blue"}},
    )

    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret
    assert render_headers(
        integration.header_template, secret, extra_values={"user_email": user.email}
    ) == {"X-Team": "blue", "X-User": user.email}


def test_mcp_config_no_sign_in_with_rejected_user_values_needs_reconnect(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session, auth_mode=IntegrationAuthMode.NONE, auth_method=None
    )
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.MCP_CONFIG,
        {"headers": {}, "header_template": {"X-Team": "{team}"}},
    )
    tagged = make_test_user("legacy_mcp_none_tagged")
    _seed(
        db_session,
        integration,
        tagged.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {"X-Team": "blue"},
            "header_substitutions": {"team": "blue"},
            "reauth_required": True,
        },
    )
    marked = make_test_user("legacy_mcp_none_marked")
    row = _seed(
        db_session,
        integration,
        marked.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {"headers": {"X-Team": "red"}, "header_substitutions": {"team": "red"}},
    )
    mark_connection_needs_reconnect__no_commit(db_session, row, "Key expired")
    db_session.commit()

    for user in (tagged, marked):
        problem = expect_problem(resolve_connection(integration, user, db_session))
        assert problem.code is ConnectionState.NEEDS_RECONNECT
        status = integration_status(integration, user, db_session)
        assert (status.state, status.reason) == (problem.code, problem.reason)


def test_individual_custom_app_user_without_row_uses_full_organization_values(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Key": "{api_key}", "X-Region": "{region}"},
    )
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.EXTERNAL_APP_ORG,
        {"api_key": "org-key", "region": "eu"},
    )
    user = make_test_user("legacy_custom_app_no_row")

    secret = expect_resolved(resolve_connection(integration, user, db_session)).secret
    assert render_headers(integration.header_template, secret) == {
        "X-Key": "org-key",
        "X-Region": "eu",
    }
    assert (
        integration_status(integration, user, db_session).state
        is ConnectionState.CONNECTED
    )
    assert expect_problem(resolve_connection(integration, None, db_session)).code is (
        ConnectionState.NOT_CONNECTED
    )


def test_custom_app_user_without_row_needs_reconnect_after_settings_change(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_app_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Key": "{api_key}"},
    )
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.EXTERNAL_APP_ORG,
        {"api_key": "org-key"},
    )
    mark_sign_in_settings_changed(integration.id, db_session)
    db_session.commit()
    user = make_test_user("legacy_custom_app_marked_org")

    problem = expect_problem(resolve_connection(integration, user, db_session))
    assert problem.code is ConnectionState.NEEDS_RECONNECT
    status = integration_status(integration, user, db_session)
    assert (status.state, status.reason) == (problem.code, problem.reason)


def test_mcp_config_no_sign_in_without_user_values_is_not_connected(
    db_session: Session,
    make_test_user: MakeTestUser,
) -> None:
    integration, _ = make_mcp_integration(
        db_session, auth_mode=IntegrationAuthMode.NONE, auth_method=None
    )
    _seed(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.MCP_CONFIG,
        {"headers": {}, "header_template": {"X-Team": "{team}", "X-Env": "{env}"}},
    )
    no_row = make_test_user("legacy_mcp_none_no_row")
    partial = make_test_user("legacy_mcp_none_partial")
    _seed(
        db_session,
        integration,
        partial.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {"headers": {}, "header_substitutions": {"team": "blue"}},
    )

    for user in (no_row, partial):
        problem = expect_problem(resolve_connection(integration, user, db_session))
        assert problem.code is ConnectionState.NOT_CONNECTED
        status = integration_status(integration, user, db_session)
        assert status.state is ConnectionState.NOT_CONNECTED
        assert status.reason == problem.reason
