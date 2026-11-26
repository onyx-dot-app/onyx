"""Common admin and member edits of integrations that the integration tables
migration copied. Rows are seeded as the migration leaves them: no header
template or credential fields where the migration writes none, and each
connection and OAuth client in its legacy format. Each edit must succeed,
keep each stored secret, and keep the headers that a chat tool or the
sandbox proxy sends."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationLegacyFormat,
    IntegrationOAuthProviderMode,
)
from onyx.db.models import (
    Integration,
    IntegrationConnection,
    IntegrationOAuthClient,
    OAuthAccount,
    User,
)
from onyx.db.persona import upsert_persona
from onyx.integrations.call_credentials import resolve_call_credentials
from onyx.integrations.connection_models import ConnectionState, read_oauth_client
from onyx.integrations.connections import ConnectionProblem
from onyx.integrations.models import EffectivePolicy, PersonaIntegrationLink
from onyx.server.features.integrations import admin_api, api
from onyx.server.features.integrations.models import (
    ConnectionFieldsRequest,
    IntegrationActionsUpdate,
    IntegrationUpdate,
    McpServerConfigInput,
    OpenApiConfigInput,
    OpenApiConfigView,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    give_access,
    make_app_integration,
    make_mcp_integration,
    make_openapi_integration,
)
from tests.external_dependency_unit.integrations.conftest import new_oauth_client

# Old releases kept a server URL with a trailing slash. The admin page saves
# an endpoint change with the base URL without it.
LEGACY_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Legacy", "version": "1"},
    "servers": [{"url": "https://legacy.example.com/v1/"}],
    "paths": {"/items": {"get": {"operationId": "list_items", "summary": "List"}}},
}
MCP_URL = "https://legacy-mcp.example.test/mcp"


@dataclass
class Seeded:
    integration: Integration
    # Whose call the chat tool and the proxy resolve.
    caller: User
    headers: dict[str, str]


def _future(hours: int = 1) -> float:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).timestamp()


def _seed_connection(
    db_session: Session,
    integration: Integration,
    user_id: UUID | None,
    legacy_format: IntegrationLegacyFormat,
    old_secret: dict[str, Any],
) -> None:
    db_session.add(
        IntegrationConnection(
            integration_id=integration.id,
            user_id=user_id,
            secret=old_secret,
            legacy_format=legacy_format.value,
            status=IntegrationConnectionStatus.CONNECTED,
        )
    )
    db_session.commit()


def _rest_tool_headers(db_session: Session, member: User) -> Seeded:
    integration, _ = make_openapi_integration(
        db_session,
        openapi_schema=LEGACY_SPEC,
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
            "headers": json.dumps([{"key": "X-Api-Key", "value": "abc{1}"}]),
        },
    )
    db_session.commit()
    return Seeded(integration, member, {"X-Api-Key": "abc{1}"})


def _rest_passthrough(db_session: Session, member: User) -> Seeded:
    integration, _ = make_openapi_integration(
        db_session,
        openapi_schema=LEGACY_SPEC,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
        header_template={"X-Static": "v{{1}}"},
    )
    db_session.add(
        OAuthAccount(
            user_id=member.id,
            oauth_name="openid",
            access_token="sso-token",
            refresh_token="",
            expires_at=int(_future(hours=24)),
            account_id=f"sso-{uuid4().hex[:8]}",
            account_email=member.email,
        )
    )
    db_session.commit()
    db_session.refresh(member)
    return Seeded(
        integration,
        member,
        {"X-Static": "v{1}", "Authorization": "Bearer sso-token"},
    )


def _rest_oauth(db_session: Session, member: User) -> Seeded:
    integration, _ = make_openapi_integration(
        db_session,
        openapi_schema=LEGACY_SPEC,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
    )
    oauth_client = new_oauth_client(
        IntegrationOAuthProviderMode.MANUAL,
        client_id="legacy-client",
        client_secret="legacy-secret",
        scopes=["repo"],
    )
    oauth_client.integration_id = integration.id
    db_session.add(oauth_client)
    db_session.commit()
    _seed_connection(
        db_session,
        integration,
        member.id,
        IntegrationLegacyFormat.OAUTH_USER_TOKEN,
        {
            "access_token": "user-access",
            "refresh_token": "user-refresh",
            "token_type": "Bearer",
            "expires_at": int(_future()),
            "scope": "repo",
        },
    )
    return Seeded(integration, member, {"Authorization": "Bearer user-access"})


def _mcp_shared_key(db_session: Session, member: User) -> Seeded:
    integration, _ = make_mcp_integration(
        db_session,
        server_url=MCP_URL,
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    _seed_connection(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {"Authorization": "Bearer sk-1"},
            "header_substitutions": {},
            "api_token": "sk-1",
        },
    )
    return Seeded(integration, member, {"Authorization": "Bearer sk-1"})


def _mcp_individual_key(db_session: Session, member: User) -> Seeded:
    # The app step of the migration copies the template and its fields.
    integration, _ = make_mcp_integration(
        db_session,
        server_url=MCP_URL,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Bearer {api_key}"},
    )
    integration.credential_fields = [
        {"key": "api_key", "label": "api key", "secret": True}
    ]
    db_session.commit()
    _seed_connection(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.MCP_CONFIG,
        {"headers": {"Authorization": "Bearer {api_key}"}},
    )
    _seed_connection(
        db_session,
        integration,
        member.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {"Authorization": "Bearer user-key"},
            "header_substitutions": {"api_key": "user-key"},
        },
    )
    return Seeded(integration, member, {"Authorization": "Bearer user-key"})


def _mcp_oauth(db_session: Session, member: User) -> Seeded:
    integration, _ = make_mcp_integration(
        db_session,
        server_url=MCP_URL,
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
                    "authorization_endpoint": "https://mcp-auth.example.test/a",
                    "token_endpoint": "https://mcp-auth.example.test/t",
                },
            },
        ),
    )
    oauth_client = db_session.scalar(
        select(IntegrationOAuthClient).where(
            IntegrationOAuthClient.integration_id == integration.id
        )
    )
    assert oauth_client is not None
    oauth_client.legacy_format = IntegrationLegacyFormat.MCP_CONFIG.value
    db_session.commit()
    _seed_connection(
        db_session,
        integration,
        member.id,
        IntegrationLegacyFormat.MCP_CONFIG,
        {
            "headers": {"Authorization": "Bearer a1"},
            "tokens": {
                "access_token": "a1",
                "refresh_token": "r1",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            "token_expires_at": _future(),
        },
    )
    return Seeded(integration, member, {"Authorization": "Bearer a1"})


def _preset(db_session: Session, member: User) -> Seeded:
    integration, _ = make_app_integration(
        db_session,
        app_type=ExternalAppType.ZENDESK,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        header_template={"Authorization": "Bearer {access_token}"},
        oauth_client=new_oauth_client(
            IntegrationOAuthProviderMode.PRESET,
            registration={
                "client_id": "zd-client",
                "client_secret": "zd-secret",
                "subdomain": "acme",
            },
        ),
    )
    oauth_client = db_session.scalar(
        select(IntegrationOAuthClient).where(
            IntegrationOAuthClient.integration_id == integration.id
        )
    )
    assert oauth_client is not None
    oauth_client.legacy_format = IntegrationLegacyFormat.EXTERNAL_APP_ORG.value
    db_session.commit()
    _seed_connection(
        db_session,
        integration,
        member.id,
        IntegrationLegacyFormat.EXTERNAL_APP_USER,
        {
            "access_token": "zd-access",
            "refresh_token": "zd-refresh",
            "token_type": "Bearer",
            "expires_at": datetime.fromtimestamp(_future(), timezone.utc).isoformat(),
        },
    )
    return Seeded(integration, member, {"Authorization": "Bearer zd-access"})


def _custom_shared(db_session: Session, member: User) -> Seeded:
    template = {"X-Key": "{api_key}"}
    integration, _ = make_app_integration(
        db_session,
        upstream_url_patterns=["https://api.legacy-custom.example.com/*"],
        auth_template=dict(template),
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template=dict(template),
    )
    _seed_connection(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.EXTERNAL_APP_ORG,
        {"api_key": "org-key"},
    )
    return Seeded(integration, member, {"X-Key": "org-key"})


def _custom_individual(db_session: Session, member: User) -> Seeded:
    template = {"X-Key": "{api_key}", "X-Region": "{region}"}
    integration, _ = make_app_integration(
        db_session,
        upstream_url_patterns=["https://api.legacy-custom.example.com/*"],
        auth_template=dict(template),
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template=dict(template),
    )
    _seed_connection(
        db_session,
        integration,
        None,
        IntegrationLegacyFormat.EXTERNAL_APP_ORG,
        {"api_key": "org-key", "region": "eu"},
    )
    _seed_connection(
        db_session,
        integration,
        member.id,
        IntegrationLegacyFormat.EXTERNAL_APP_USER,
        {"api_key": "user-key", "region": "us"},
    )
    return Seeded(integration, member, {"X-Key": "user-key", "X-Region": "us"})


SEEDS: dict[str, Callable[[Session, User], Seeded]] = {
    "rest_tool_headers": _rest_tool_headers,
    "rest_passthrough": _rest_passthrough,
    "rest_oauth": _rest_oauth,
    "mcp_shared_key": _mcp_shared_key,
    "mcp_individual_key": _mcp_individual_key,
    "mcp_oauth": _mcp_oauth,
    "preset": _preset,
    "custom_shared": _custom_shared,
    "custom_individual": _custom_individual,
}


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("medit-admin", is_admin=True)


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("medit-member")


def _seed(db_session: Session, name: str, member: User) -> Seeded:
    seeded = SEEDS[name](db_session, member)
    give_access(db_session, [seeded.integration])
    return seeded


def _secrets(db_session: Session, integration_id: int) -> dict[UUID | None, Any]:
    db_session.expire_all()
    rows = db_session.scalars(
        select(IntegrationConnection).where(
            IntegrationConnection.integration_id == integration_id
        )
    ).all()
    for row in rows:
        assert row.status is IntegrationConnectionStatus.CONNECTED, row.user_id
    return {row.user_id: row.secret.get_value(apply_mask=False) for row in rows}


def _client_secret(db_session: Session, integration_id: int) -> tuple[Any, ...]:
    oauth_client = db_session.scalar(
        select(IntegrationOAuthClient).where(
            IntegrationOAuthClient.integration_id == integration_id
        )
    )
    if oauth_client is None:
        return ()
    credentials = read_oauth_client(oauth_client)
    return (credentials.client_id, credentials.client_secret)


def _headers(db_session: Session, seeded: Seeded) -> dict[str, str]:
    db_session.expire_all()
    integration = db_session.get(Integration, seeded.integration.id)
    assert integration is not None
    caller = db_session.get(User, seeded.caller.id)
    assert caller is not None
    credentials = resolve_call_credentials(integration, caller, db_session)
    if isinstance(credentials, ConnectionProblem):
        pytest.fail(f"expected credentials, got {credentials}")
    return credentials.headers


def _rename(db_session: Session, admin: User, integration_id: int) -> None:
    admin_api.update_integration(
        integration_id,
        IntegrationUpdate(name=f"renamed-{uuid4().hex[:6]}"),
        admin,
        db_session,
    )


def _describe(db_session: Session, admin: User, integration_id: int) -> None:
    admin_api.update_integration(
        integration_id, IntegrationUpdate(description="Edited"), admin, db_session
    )


def _switch(db_session: Session, admin: User, integration_id: int) -> None:
    for enabled in (False, True):
        admin_api.update_integration(
            integration_id, IntegrationUpdate(enabled=enabled), admin, db_session
        )


def _always_allow(db_session: Session, admin: User, integration_id: int) -> None:
    admin_api.update_integration(
        integration_id,
        IntegrationUpdate(users_can_save_always_allow=False),
        admin,
        db_session,
    )


def _action_policy(db_session: Session, admin: User, integration_id: int) -> None:
    admin_api.set_integration_actions(
        integration_id,
        IntegrationActionsUpdate(default_policy=EffectivePolicy.ASK),
        admin,
        db_session,
    )


def _agent_link(db_session: Session, admin: User, integration_id: int) -> None:
    upsert_persona(
        user=admin,
        name=f"agent-{uuid4().hex[:8]}",
        description="",
        starter_messages=None,
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        is_public=True,
        db_session=db_session,
        tool_ids=None,
        integration_links=[PersonaIntegrationLink(integration_id=integration_id)],
    )


def _same_config(db_session: Session, admin: User, integration_id: int) -> None:
    """Save the kind settings as the admin page sends them."""
    detail = admin_api.get_integration_admin(integration_id, admin, db_session)
    config = detail.config
    if isinstance(config, McpServerConfigInput):
        update = IntegrationUpdate(config=config)
    elif isinstance(config, OpenApiConfigView):
        # A new endpoint; the page sends the base URL without a trailing slash.
        update = IntegrationUpdate(
            config=OpenApiConfigInput(
                openapi_document=config.openapi_document,
                base_url=config.base_url.rstrip("/"),
                endpoints=[*config.endpoints, "GET /status Get status"],
            )
        )
    else:
        return
    admin_api.update_integration(integration_id, update, admin, db_session)


EDITS: dict[str, Callable[[Session, User, int], None]] = {
    "rename": _rename,
    "description": _describe,
    "enable_switch": _switch,
    "always_allow": _always_allow,
    "action_policy": _action_policy,
    "agent_link": _agent_link,
    "kind_settings": _same_config,
}


@pytest.mark.parametrize("edit", list(EDITS))
@pytest.mark.parametrize("seed", list(SEEDS))
def test_an_edit_keeps_the_migrated_credential(
    db_session: Session, admin: User, member: User, seed: str, edit: str
) -> None:
    seeded = _seed(db_session, seed, member)
    integration_id = seeded.integration.id
    assert _headers(db_session, seeded) == seeded.headers
    secrets = _secrets(db_session, integration_id)
    client = _client_secret(db_session, integration_id)

    EDITS[edit](db_session, admin, integration_id)

    assert _secrets(db_session, integration_id) == secrets
    assert _client_secret(db_session, integration_id) == client
    assert _headers(db_session, seeded) == seeded.headers
    admin_api.get_integration_admin(integration_id, admin, db_session)


@pytest.mark.parametrize("seed", ["mcp_individual_key", "custom_individual"])
def test_a_member_connect_and_disconnect_keep_the_migrated_credentials(
    db_session: Session,
    member: User,
    make_test_user: MakeTestUser,
    seed: str,
) -> None:
    seeded = _seed(db_session, seed, member)
    integration_id = seeded.integration.id
    secrets = _secrets(db_session, integration_id)
    other = make_test_user("medit-other")
    detail = api.get_integration_for_member(integration_id, other, db_session)
    fields = {field.key: f"new-{field.key}" for field in detail.credential_fields}

    with patch(
        "onyx.integrations.kinds.mcp_server.discover_mcp_tools", return_value=[]
    ):
        status = api.save_member_connection(
            integration_id, ConnectionFieldsRequest(fields=fields), other, db_session
        )
    assert status.state is ConnectionState.CONNECTED
    api.delete_member_connection(integration_id, other, db_session)

    assert _secrets(db_session, integration_id) == secrets
    assert _headers(db_session, seeded) == seeded.headers
