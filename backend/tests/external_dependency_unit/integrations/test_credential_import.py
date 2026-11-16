"""The one-time import moves each old credential source into the integration
tables, once."""

import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text, update
from sqlalchemy.orm import Session

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
from onyx.db.integration_connection import (
    get_connection,
    get_oauth_client,
    list_connections_for_integration,
)
from onyx.db.models import (
    ExternalApp,
    ExternalAppUserCredential,
    Integration,
    MCPConnectionConfig,
    MCPServer,
    OAuthConfig,
    OAuthUserToken,
    Tool,
    User,
)
from onyx.integrations.connection_models import (
    SIGN_IN_EXPIRED_REASON,
    ConnectionSecret,
    read_connection_secret,
)
from onyx.integrations.connections import credential_import_done, disconnect
from onyx.integrations.credential_import import (
    import_legacy_credentials,
    run_credential_import_if_needed,
)
from onyx.server.features.mcp.oauth import (
    INTEGRATION_CLIENT_INFO_KEY,
    INTEGRATION_OAUTH_METADATA_KEY,
)
from onyx.utils.encryption import decrypt_bytes_to_string
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integrations.conftest import MakeIntegration

_BEARER = {"Authorization": "Bearer {access_token}"}


class _Sources(BaseModel):
    model_config = {"arbitrary_types_allowed": True}

    mcp_shared: Integration
    mcp_per_user: Integration
    tool_oauth: Integration
    tool_headers: Integration
    app_preset: Integration
    app_custom_shared: Integration
    app_custom_individual: Integration
    user_a: User
    user_b: User
    inactive_user: User

    def integrations(self) -> list[Integration]:
        return [
            self.mcp_shared,
            self.mcp_per_user,
            self.tool_oauth,
            self.tool_headers,
            self.app_preset,
            self.app_custom_shared,
            self.app_custom_individual,
        ]


def _make_sources(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    legacy_rows: list[object],
) -> _Sources:
    user_a = make_test_user("import_a")
    user_b = make_test_user("import_b")
    # Emails are unique and lowercase, so a second match can only be an
    # inactive user.
    inactive = make_test_user("import_inactive")
    db_session.execute(
        update(User).where(User.__table__.c.id == inactive.id).values(is_active=False)
    )
    db_session.commit()
    future = time.time() + 3600

    # 1. MCP admin connection config: shared OAuth with a DCR client.
    mcp_shared = make_integration(
        kind=IntegrationKind.MCP_SERVER,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.DISCOVERY,
    )
    server_shared = MCPServer(
        owner=user_a.email,
        name=f"mcp-shared-{mcp_shared.id}",
        server_url="https://mcp-shared.example.test/mcp",
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        integration_id=mcp_shared.id,
    )
    db_session.add(server_shared)
    db_session.flush()
    legacy_rows.append(server_shared)
    admin_config = MCPConnectionConfig(
        mcp_server_id=server_shared.id,
        user_email="",
        config={
            "headers": {"Authorization": "Bearer org-access"},
            "client_info": {
                "client_id": "dcr-client",
                "redirect_uris": ["https://onyx.example.test/mcp/oauth/callback"],
                "token_endpoint_auth_method": "none",
            },
            "metadata": {
                "issuer": "https://auth.example.test",
                "authorization_endpoint": "https://auth.example.test/authorize",
                "token_endpoint": "https://auth.example.test/token",
            },
            "tokens": {
                "access_token": "org-access",
                "refresh_token": "org-refresh",
                "token_type": "Bearer",
            },
            "token_expires_at": future,
        },
    )
    db_session.add(admin_config)
    db_session.flush()
    server_shared.admin_connection_config_id = admin_config.id

    # 2. MCP user configs keyed by email: per-user API keys.
    mcp_per_user = make_integration(
        kind=IntegrationKind.MCP_SERVER,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    server_per_user = MCPServer(
        owner=user_a.email,
        name=f"mcp-user-{mcp_per_user.id}",
        server_url="https://mcp-user.example.test/mcp",
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        integration_id=mcp_per_user.id,
    )
    db_session.add(server_per_user)
    db_session.flush()
    legacy_rows.append(server_per_user)
    template_config = MCPConnectionConfig(
        mcp_server_id=server_per_user.id,
        user_email="",
        config={"headers": {}, "header_template": {"X-Key": "{api_key}"}},
    )
    db_session.add(template_config)
    db_session.flush()
    server_per_user.admin_connection_config_id = template_config.id
    for email, key in (
        # Old rows can hold the email in another case.
        (user_a.email.upper(), "key-a"),
        ("nobody-" + user_a.email, "key-nobody"),
        (inactive.email, "key-inactive"),
    ):
        db_session.add(
            MCPConnectionConfig(
                mcp_server_id=server_per_user.id,
                user_email=email,
                config={
                    "headers": {"X-Key": key},
                    "header_substitutions": {"api_key": key},
                },
            )
        )

    # 3 and 4. oauth_config client and oauth_user_token rows.
    tool_oauth = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        provider_mode=IntegrationOAuthProviderMode.MANUAL,
    )
    oauth_config = OAuthConfig(
        name=f"oauth-config-{tool_oauth.id}",
        authorization_url="https://auth.example.test/authorize",
        token_url="https://auth.example.test/token",
        client_id="config-client",
        client_secret="config-secret",
    )
    db_session.add(oauth_config)
    db_session.flush()
    legacy_rows.append(oauth_config)
    oauth_tool = Tool(
        name=f"oauth-tool-{tool_oauth.id}",
        description="",
        openapi_schema={"openapi": "3.0.0"},
        custom_headers=[],
        passthrough_auth=False,
        oauth_config_id=oauth_config.id,
        integration_id=tool_oauth.id,
    )
    db_session.add(oauth_tool)
    legacy_rows.append(oauth_tool)
    db_session.add(
        OAuthUserToken(
            oauth_config_id=oauth_config.id,
            user_id=user_a.id,
            token_data={
                "access_token": "tool-a",
                "refresh_token": "tool-a-refresh",
                "token_type": "Bearer",
                "expires_at": int(future),
            },
        )
    )
    db_session.add(
        OAuthUserToken(
            oauth_config_id=oauth_config.id,
            user_id=user_b.id,
            token_data={"access_token": "tool-b", "expires_at": int(time.time()) - 60},
        )
    )

    # 5. Plain custom headers of an OpenAPI tool.
    tool_headers = make_integration(
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    headers_tool = Tool(
        name=f"headers-tool-{tool_headers.id}",
        description="",
        openapi_schema={"openapi": "3.0.0"},
        custom_headers=[{"key": "X-Secret", "value": "plain-secret"}],
        passthrough_auth=False,
        integration_id=tool_headers.id,
    )
    db_session.add(headers_tool)
    legacy_rows.append(headers_tool)

    # 6 and 7. External app organization and user credentials.
    app_preset = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template=_BEARER,
        provider_mode=IntegrationOAuthProviderMode.PRESET,
    )
    preset_app = ExternalApp(
        name=f"Linear {app_preset.id}",
        app_type=ExternalAppType.LINEAR,
        upstream_url_patterns=[],
        auth_template=_BEARER,
        organization_credentials={
            "client_id": "linear-client",
            "client_secret": "linear-secret",
        },
        integration_id=app_preset.id,
    )
    app_custom_shared = make_integration(
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    custom_shared_app = ExternalApp(
        name=f"Custom shared {app_custom_shared.id}",
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[],
        auth_template={"Authorization": "Bearer {api_key}"},
        organization_credentials={"api_key": "org-key"},
        integration_id=app_custom_shared.id,
    )
    app_custom_individual = make_integration(
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    custom_individual_app = ExternalApp(
        name=f"Custom individual {app_custom_individual.id}",
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[],
        auth_template={"Authorization": "Bearer {api_key}", "X-Org": "{org_id}"},
        organization_credentials={"org_id": "org-1"},
        integration_id=app_custom_individual.id,
    )
    for app in (preset_app, custom_shared_app, custom_individual_app):
        db_session.add(app)
        db_session.flush()
        legacy_rows.append(app)
    db_session.add(
        ExternalAppUserCredential(
            external_app_id=preset_app.id,
            user_id=user_a.id,
            user_credentials={
                "access_token": "linear-a",
                "refresh_token": "linear-a-refresh",
                "token_type": "Bearer",
                "scope": "read",
                "expires_at": (
                    datetime.now(timezone.utc) + timedelta(hours=1)
                ).isoformat(),
            },
            granted_scopes=["read"],
        )
    )
    db_session.add(
        ExternalAppUserCredential(
            external_app_id=custom_individual_app.id,
            user_id=user_b.id,
            user_credentials={"api_key": "user-key"},
        )
    )
    db_session.commit()
    return _Sources(
        mcp_shared=mcp_shared,
        mcp_per_user=mcp_per_user,
        tool_oauth=tool_oauth,
        tool_headers=tool_headers,
        app_preset=app_preset,
        app_custom_shared=app_custom_shared,
        app_custom_individual=app_custom_individual,
        user_a=user_a,
        user_b=user_b,
        inactive_user=inactive,
    )


def _secret(
    db_session: Session, integration: Integration, user: User | None
) -> ConnectionSecret:
    connection = get_connection(
        db_session, integration.id, user.id if user is not None else None
    )
    assert connection is not None
    return read_connection_secret(connection)


def _client_values(
    db_session: Session, integration: Integration
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    oauth_client = get_oauth_client(db_session, integration.id)
    assert oauth_client is not None
    return (
        oauth_client.client_id.get_value(apply_mask=False)
        if oauth_client.client_id is not None
        else None,
        oauth_client.client_secret.get_value(apply_mask=False)
        if oauth_client.client_secret is not None
        else None,
        oauth_client.registration.get_value(apply_mask=False)
        if oauth_client.registration is not None
        else None,
    )


def _snapshot(db_session: Session, sources: _Sources) -> list[tuple[Any, ...]]:
    db_session.expire_all()
    rows: list[tuple[Any, ...]] = []
    for integration in sources.integrations():
        db_session.refresh(integration)
        rows.append(
            (
                integration.id,
                integration.auth_mode,
                integration.auth_method,
                json.dumps(integration.header_template, sort_keys=True),
                _client_values(db_session, integration)
                if get_oauth_client(db_session, integration.id) is not None
                else None,
            )
        )
        rows.extend(
            (
                connection.id,
                connection.user_id,
                connection.status,
                connection.updated_at,
                read_connection_secret(connection).model_dump_json(),
            )
            for connection in list_connections_for_integration(
                db_session, integration.id
            )
        )
    return rows


def test_import_moves_each_source_and_second_run_changes_nothing(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    legacy_rows: list[object],
) -> None:
    sources = _make_sources(db_session, make_integration, make_test_user, legacy_rows)

    first = import_legacy_credentials(db_session)
    assert first.inserted >= 8
    db_session.expire_all()

    # 1. MCP admin config: OAuth client, organization row, header template.
    client_id, _, registration = _client_values(db_session, sources.mcp_shared)
    assert client_id == "dcr-client"
    assert registration is not None
    assert registration[INTEGRATION_CLIENT_INFO_KEY]["client_id"] == "dcr-client"
    assert (
        registration[INTEGRATION_OAUTH_METADATA_KEY]["token_endpoint"]
        == "https://auth.example.test/token"
    )
    org_secret = _secret(db_session, sources.mcp_shared, None)
    assert (org_secret.access_token, org_secret.refresh_token) == (
        "org-access",
        "org-refresh",
    )
    assert sources.mcp_shared.header_template == _BEARER

    # 2. MCP user configs: only the email of exactly one active user. The
    # email of no user and of an inactive user are skipped.
    connections = list_connections_for_integration(db_session, sources.mcp_per_user.id)
    assert [connection.user_id for connection in connections] == [sources.user_a.id]
    assert read_connection_secret(connections[0]).fields == {"api_key": "key-a"}
    assert sources.mcp_per_user.header_template == {"X-Key": "{api_key}"}

    # 3. oauth_config client id and secret.
    assert _client_values(db_session, sources.tool_oauth)[:2] == (
        "config-client",
        "config-secret",
    )
    assert sources.tool_oauth.header_template == _BEARER

    # 4. oauth_user_token: a live token and a dead one.
    live = get_connection(db_session, sources.tool_oauth.id, sources.user_a.id)
    assert live is not None
    assert live.status is IntegrationConnectionStatus.CONNECTED
    assert read_connection_secret(live).refresh_token == "tool-a-refresh"
    dead = get_connection(db_session, sources.tool_oauth.id, sources.user_b.id)
    assert dead is not None
    assert dead.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    assert dead.status_reason == SIGN_IN_EXPIRED_REASON

    # 5. Custom tool headers end encrypted on the organization row.
    assert _secret(db_session, sources.tool_headers, None).fields == {
        "X-Secret": "plain-secret"
    }
    assert sources.tool_headers.header_template == {"X-Secret": "{X-Secret}"}
    raw = db_session.execute(
        text(
            "SELECT secret FROM integration_connection "
            "WHERE integration_id = :id AND user_id IS NULL"
        ),
        {"id": sources.tool_headers.id},
    ).scalar_one()
    assert isinstance(raw, (bytes, memoryview))
    assert json.loads(decrypt_bytes_to_string(bytes(raw)))["fields"] == {
        "X-Secret": "plain-secret"
    }

    # 6. External app organization credentials.
    assert _client_values(db_session, sources.app_preset)[:2] == (
        "linear-client",
        "linear-secret",
    )
    assert sources.app_custom_shared.auth_mode is IntegrationAuthMode.SHARED
    assert _secret(db_session, sources.app_custom_shared, None).fields == {
        "api_key": "org-key"
    }

    # 7. External app user credentials.
    preset_row = get_connection(db_session, sources.app_preset.id, sources.user_a.id)
    assert preset_row is not None
    assert read_connection_secret(preset_row).access_token == "linear-a"
    assert preset_row.granted_scopes == ["read"]
    assert preset_row.expires_at is not None
    assert sources.app_custom_individual.auth_mode is IntegrationAuthMode.INDIVIDUAL
    assert _secret(
        db_session, sources.app_custom_individual, sources.user_b
    ).fields == {
        "org_id": "org-1",
        "api_key": "user-key",
    }
    assert get_connection(db_session, sources.app_custom_individual.id, None) is None

    before = _snapshot(db_session, sources)
    second = import_legacy_credentials(db_session)
    assert second.inserted == 0
    assert _snapshot(db_session, sources) == before


def test_user_who_disconnects_after_import_stays_disconnected(
    db_session: Session,
    make_integration: MakeIntegration,
    make_test_user: MakeTestUser,
    legacy_rows: list[object],
    import_flag: Callable[[bool], None],
) -> None:
    sources = _make_sources(db_session, make_integration, make_test_user, legacy_rows)
    import_flag(False)

    assert run_credential_import_if_needed(db_session) is True
    assert credential_import_done()
    assert get_connection(db_session, sources.app_preset.id, sources.user_a.id)

    disconnect(sources.app_preset, sources.user_a, db_session)
    assert run_credential_import_if_needed(db_session) is False
    assert get_connection(db_session, sources.app_preset.id, sources.user_a.id) is None
