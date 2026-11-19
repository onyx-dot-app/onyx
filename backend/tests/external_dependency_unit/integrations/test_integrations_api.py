"""The integration API, called through its route functions against the
database: create of each kind, the permission rules, sign-in changes, the
actions, the member choices, the agent integrations and the public tool aliases."""

import json
from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import ConnectError, HTTPStatusError, Request, Response
from mcp.types import Tool as MCPLibTool
from mcp.types import ToolAnnotations
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    PluginInstallationPolicy,
)
from onyx.db.integration import (
    get_external_app_for_integration,
    get_integration_by_kind_row,
    get_mcp_server_for_integration,
    get_openapi_tool_for_integration,
    list_integration_actions,
)
from onyx.db.integration_connection import get_connection, get_oauth_client
from onyx.db.integration_policy import list_persona_integration_links
from onyx.db.models import (
    ExternalApp,
    Integration,
    Integration__User,
    IntegrationOAuthClient,
    Marketplace,
    MCPServer,
    Persona,
    Plugin,
    Tool,
    User,
)
from onyx.db.persona import upsert_persona
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import WHOLE_DOMAIN_ACTION_TYPE
from onyx.integrations.connection_models import (
    ConnectionSecret,
    ConnectionState,
    read_connection_secret,
)
from onyx.integrations.connections import (
    connect_with_fields__no_commit,
    integration_status,
)
from onyx.integrations.models import (
    IntegrationActionSpec,
    PersonaIntegrationLink,
)
from onyx.integrations.oauth import start_integration_oauth
from onyx.server.features.integrations import admin_api, api
from onyx.server.features.integrations.models import (
    ActionGrantsUpdate,
    ConnectionFieldsRequest,
    CredentialField,
    CustomConfigInput,
    IntegrationActionsUpdate,
    IntegrationCreate,
    IntegrationShape,
    IntegrationUpdate,
    McpServerConfigInput,
    OAuthClientInput,
    OpenApiConfigInput,
    PresetConfigInput,
)
from onyx.server.features.persona import api as persona_api
from onyx.server.features.tool import api as tool_api
from onyx.server.features.tool.models import (
    CustomToolCreate,
    CustomToolUpdate,
    Header,
)
from onyx.utils.encryption import mask_string
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    give_access,
    make_mcp_integration,
)

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Weather", "description": "Weather", "version": "1.0"},
    "servers": [{"url": "https://weather.example.com"}],
    "paths": {
        "/forecast": {
            "get": {"operationId": "get_forecast", "summary": "Get the forecast"},
            "post": {"operationId": "set_alert", "summary": "Set an alert"},
        }
    },
}


class Created:
    def __init__(self) -> None:
        self.ids: list[int] = []

    def add(self, integration_id: int) -> int:
        self.ids.append(integration_id)
        return integration_id


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("u6-admin", is_admin=True)


@pytest.fixture
def scoped(make_test_user: MakeTestUser, db_session: Session) -> User:
    user = make_test_user("u6-scoped")
    user.is_group_manager = True
    db_session.commit()
    return user


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("u6-member")


@pytest.fixture
def created(
    db_session: Session,
    admin: User,  # noqa: ARG001
    scoped: User,  # noqa: ARG001
    member: User,  # noqa: ARG001
) -> Generator[Created, None, None]:
    """Integrations a test makes; deleted before the users."""
    tracker = Created()
    try:
        yield tracker
    finally:
        delete_integrations(db_session, tracker.ids)


@pytest.fixture
def craft_available() -> Generator[None, None, None]:
    with patch(
        "onyx.integrations.service.is_craft_available_for_deployment",
        return_value=True,
    ):
        yield


def _openapi_create(
    *, for_organization: bool = True, name: str | None = None
) -> IntegrationCreate:
    return IntegrationCreate(
        for_organization=for_organization,
        name=name or f"weather-{uuid4().hex[:8]}",
        description="Forecasts",
        auth_mode=IntegrationAuthMode.SHARED,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"X-Api-Key": "{api_key}"},
        config=OpenApiConfigInput(openapi_spec=OPENAPI_SPEC),
    )


def _plugin_rows(db_session: Session) -> tuple[int, int]:
    """The count of plugins and of marketplaces."""
    return (
        db_session.scalar(select(func.count()).select_from(Plugin)) or 0,
        db_session.scalar(select(func.count()).select_from(Marketplace)) or 0,
    )


def _make_available(db_session: Session, integration_id: int) -> None:
    """Make the integration Available to the organization."""
    integration = db_session.get(Integration, integration_id)
    assert integration is not None
    integration.installation_policy = PluginInstallationPolicy.AVAILABLE
    db_session.commit()


# Create


def test_create_openapi_makes_integration_tool_and_actions_and_no_plugin(
    db_session: Session, admin: User, created: Created
) -> None:
    plugin_rows = _plugin_rows(db_session)
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)

    assert detail.kind is IntegrationKind.API
    assert detail.shape is IntegrationShape.OPENAPI
    assert detail.credential_fields[0].key == "api_key"
    assert detail.needs_setup is True
    assert detail.can_manage is True
    tool = get_openapi_tool_for_integration(detail.id, db_session)
    assert tool is not None and tool.openapi_schema == OPENAPI_SPEC
    assert _plugin_rows(db_session) == plugin_rows
    assert detail.installation_policy is PluginInstallationPolicy.AVAILABLE
    assert detail.access.shared_with_everyone is True
    actions = {
        action.key: action for action in list_integration_actions(detail.id, db_session)
    }
    assert set(actions) == {"get_forecast", "set_alert"}
    assert detail.action_count == 2


def test_a_personal_integration_starts_on_for_its_creator(
    db_session: Session, scoped: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), scoped, db_session
    )
    created.add(detail.id)

    view = api.get_integration_for_member(detail.id, scoped, db_session)
    assert (view.access.owner_email, view.access.user_enabled) == (scoped.email, True)
    assert view.access.shared_with_everyone is False


def test_a_header_change_keeps_the_stored_credential_fields(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            credential_fields=[
                CredentialField(key="api_key", label="Weather key", secret=False)
            ]
        ),
        admin,
        db_session,
    )

    updated = admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            header_template={
                "X-Api-Key": "{api_key}",
                "X-Region": "{region}",
                "X-Team": "blue",
            }
        ),
        admin,
        db_session,
    )

    assert [
        (field.key, field.label, field.secret) for field in updated.credential_fields
    ] == [("api_key", "Weather key", False), ("region", "region", True)]


def test_a_spec_with_no_server_url_does_not_break_the_admin_list(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    tool = get_openapi_tool_for_integration(detail.id, db_session)
    assert tool is not None
    tool.openapi_schema = {**OPENAPI_SPEC, "servers": []}
    db_session.commit()

    listed = admin_api.list_integrations_admin(admin, db_session)

    assert detail.id in {view.id for view in listed}


def test_create_mcp_discovers_tools_of_a_public_server(
    db_session: Session, scoped: User, created: Created
) -> None:
    def discover(*_args: Any, **_kwargs: Any) -> list[MCPLibTool]:
        assert (
            db_session.scalar(
                select(MCPServer.id).where(
                    MCPServer.server_url == "https://mcp.example.com/mcp"
                )
            )
            is None
        )
        return [
            MCPLibTool(
                name="search",
                inputSchema={"type": "object"},
                annotations=ToolAnnotations(readOnlyHint=True),
            )
        ]

    plugin_rows = _plugin_rows(db_session)
    with patch(
        "onyx.integrations.service.discover_mcp_tools", side_effect=discover
    ) as fetch:
        detail = admin_api.create_integration(
            IntegrationCreate(
                name=f"mcp-{uuid4().hex[:8]}",
                auth_mode=IntegrationAuthMode.NONE,
                config=McpServerConfigInput(server_url="https://mcp.example.com/mcp"),
            ),
            scoped,
            db_session,
        )
    created.add(detail.id)
    fetch.assert_called_once()
    assert detail.kind is IntegrationKind.MCP
    server = get_mcp_server_for_integration(detail.id, db_session)
    assert server is not None and server.server_url == "https://mcp.example.com/mcp"
    assert [a.key for a in list_integration_actions(detail.id, db_session)] == [
        "search"
    ]
    # A private integration makes no plugin and no "My uploads".
    assert _plugin_rows(db_session) == plugin_rows
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    assert integration.owner_user_id == scoped.id
    assert integration.installation_policy is PluginInstallationPolicy.NOT_AVAILABLE
    # No MCP tool row is written.
    assert server is not None
    assert (
        db_session.scalar(select(Tool.id).where(Tool.mcp_server_id == server.id))
        is None
    )


@pytest.mark.usefixtures("craft_available")
def test_create_preset_keeps_client_and_host_on_the_oauth_client(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=True,
            name=f"zendesk-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.INDIVIDUAL,
            auth_method=IntegrationAuthMethod.OAUTH2,
            oauth_client=OAuthClientInput(
                provider_mode=IntegrationOAuthProviderMode.PRESET
            ),
            config=PresetConfigInput(
                preset_id="ZENDESK",
                organization_credentials={
                    "subdomain": "acme",
                    "client_id": "zd-client",
                    "client_secret": "zd-secret",
                },
            ),
        ),
        admin,
        db_session,
    )
    created.add(detail.id)
    assert detail.shape is IntegrationShape.PRESET
    assert detail.preset_id == "ZENDESK"
    assert detail.oauth_client is not None
    assert detail.oauth_client.client_id == "zd-client"
    assert detail.oauth_client.has_client_secret is True
    oauth_client = get_oauth_client(db_session, detail.id)
    assert oauth_client is not None
    assert oauth_client.additional_params == {"subdomain": "acme"}
    app = get_external_app_for_integration(detail.id, db_session)
    assert app is not None
    assert app.organization_credentials.get_value(apply_mask=False) == {}
    assert any("acme" in pattern for pattern in app.upstream_url_patterns)
    assert len(list_integration_actions(detail.id, db_session)) > 0


def _custom_create() -> IntegrationCreate:
    return IntegrationCreate(
        name=f"custom-{uuid4().hex[:8]}",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
        header_template={"Authorization": "Bearer {token}"},
        config=CustomConfigInput(
            upstream_url_patterns=["https://api.custom.example.com/*"]
        ),
    )


@pytest.mark.usefixtures("craft_available")
def test_create_custom_app(db_session: Session, admin: User, created: Created) -> None:
    detail = admin_api.create_integration(_custom_create(), admin, db_session)
    created.add(detail.id)
    assert detail.shape is IntegrationShape.CUSTOM
    assert detail.access.shared_with_everyone is False
    assert detail.config.shape is IntegrationShape.CUSTOM


@pytest.mark.usefixtures("craft_available")
def test_action_views_flag_the_custom_app_action_that_always_asks(
    db_session: Session, admin: User, created: Created
) -> None:
    custom = admin_api.create_integration(_custom_create(), admin, db_session)
    created.add(custom.id)
    openapi = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(openapi.id)

    custom_actions = admin_api.get_integration_actions(
        custom.id, admin, db_session
    ).actions
    assert [(a.key, a.always_asks) for a in custom_actions] == [
        (WHOLE_DOMAIN_ACTION_TYPE, True)
    ]
    member_actions = api.get_integration_for_member(custom.id, admin, db_session)
    assert [a.always_asks for a in member_actions.actions] == [True]
    openapi_actions = admin_api.get_integration_actions(
        openapi.id, admin, db_session
    ).actions
    assert openapi_actions
    assert not any(a.always_asks for a in openapi_actions)


def test_without_craft_no_external_app_and_no_presets(
    db_session: Session, admin: User
) -> None:
    preset = IntegrationCreate(
        name=f"github-{uuid4().hex[:8]}",
        auth_mode=IntegrationAuthMode.NONE,
        config=PresetConfigInput(preset_id="GITHUB"),
    )
    with patch(
        "onyx.integrations.service.is_craft_available_for_deployment",
        return_value=False,
    ):
        assert admin_api.list_integration_presets(admin) == []
        for request in (preset, _custom_create()):
            with pytest.raises(OnyxError) as error:
                admin_api.create_integration(request, admin, db_session)
            assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
            assert (
                db_session.scalar(
                    select(Integration.id).where(Integration.name == request.name)
                )
                is None
            )


def test_create_mcp_saves_nothing_when_discovery_fails(
    db_session: Session, admin: User
) -> None:
    name = f"mcp-down-{uuid4().hex[:8]}"
    with (
        patch(
            "onyx.integrations.service.discover_mcp_tools",
            side_effect=ConnectError("down"),
        ),
        pytest.raises(OnyxError) as error,
    ):
        admin_api.create_integration(
            IntegrationCreate(
                name=name,
                auth_mode=IntegrationAuthMode.NONE,
                config=McpServerConfigInput(server_url="https://mcp.example.com/mcp"),
            ),
            admin,
            db_session,
        )
    assert error.value.error_code is OnyxErrorCode.BAD_GATEWAY
    db_session.rollback()
    assert (
        db_session.scalar(select(Integration.id).where(Integration.name == name))
        is None
    )
    assert db_session.scalar(select(MCPServer.id).where(MCPServer.name == name)) is None


def test_create_rolls_back_when_a_step_fails(db_session: Session, admin: User) -> None:
    name = f"rollback-{uuid4().hex[:8]}"
    with (
        patch(
            "onyx.integrations.service.sync_integration_actions__no_commit",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError),
    ):
        admin_api.create_integration(_openapi_create(name=name), admin, db_session)
    db_session.rollback()
    assert (
        db_session.scalar(select(Integration.id).where(Integration.name == name))
        is None
    )
    assert db_session.scalar(select(Tool.id).where(Tool.name == name)) is None


@pytest.mark.parametrize(
    "config",
    [
        McpServerConfigInput(server_url="https://mcp.example.com/mcp"),
        CustomConfigInput(upstream_url_patterns=["https://api.custom.example.com/*"]),
    ],
)
@pytest.mark.usefixtures("craft_available")
def test_delete_removes_the_kind_row(
    db_session: Session,
    admin: User,
    created: Created,
    config: McpServerConfigInput | CustomConfigInput,
) -> None:
    detail = admin_api.create_integration(
        IntegrationCreate(
            name=f"delete-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.SHARED,
            auth_method=IntegrationAuthMethod.API_KEY,
            header_template={"Authorization": "Bearer {token}"},
            config=config,
        ),
        admin,
        db_session,
    )
    created.add(detail.id)
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    kind_row = (MCPServer, integration.mcp_server_id)
    if integration.external_app_id is not None:
        kind_row = (ExternalApp, integration.external_app_id)
    assert kind_row[1] is not None

    admin_api.delete_integration(detail.id, admin, db_session)

    db_session.expire_all()
    assert db_session.get(Integration, detail.id) is None
    assert db_session.get(kind_row[0], kind_row[1]) is None


# Permissions


def test_scoped_manager_cannot_add_for_the_organization(
    db_session: Session, scoped: User
) -> None:
    with pytest.raises(OnyxError) as error:
        admin_api.create_integration(_openapi_create(), scoped, db_session)
    assert error.value.status_code == 403


def test_only_global_manager_sets_onyx_login(
    db_session: Session, scoped: User, admin: User, created: Created
) -> None:
    request = IntegrationCreate(
        name=f"login-{uuid4().hex[:8]}",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.ONYX_LOGIN,
        config=OpenApiConfigInput(openapi_spec=OPENAPI_SPEC),
    )
    with pytest.raises(OnyxError) as error:
        admin_api.create_integration(request, scoped, db_session)
    assert error.value.status_code == 403
    db_session.rollback()
    created.add(admin_api.create_integration(request, admin, db_session).id)


def test_scoped_owner_manages_its_personal_integration(
    db_session: Session, scoped: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), scoped, db_session
    )
    created.add(detail.id)
    updated = admin_api.update_integration(
        detail.id, IntegrationUpdate(name="Renamed"), scoped, db_session
    )
    assert updated.name == "Renamed"
    assert updated.can_manage is True


def test_scoped_non_owner_cannot_see_or_change(
    db_session: Session, scoped: User, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), admin, db_session
    )
    created.add(detail.id)
    with pytest.raises(OnyxError) as error:
        admin_api.update_integration(
            detail.id, IntegrationUpdate(name="x"), scoped, db_session
        )
    assert error.value.status_code == 404
    assert detail.id not in {
        view.id for view in admin_api.list_integrations_admin(scoped, db_session)
    }


def test_organization_library_integration_needs_global_manager(
    db_session: Session, scoped: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), scoped, db_session
    )
    created.add(detail.id)
    _make_available(db_session, detail.id)

    view = admin_api.get_integration_admin(detail.id, scoped, db_session)
    assert view.can_manage is False
    with pytest.raises(OnyxError) as error:
        admin_api.update_integration(
            detail.id, IntegrationUpdate(name="x"), scoped, db_session
        )
    assert error.value.status_code == 403
    with pytest.raises(OnyxError):
        admin_api.delete_integration(detail.id, scoped, db_session)


def test_group_manager_of_a_shared_plugin_cannot_change_it(
    db_session: Session, scoped: User, admin: User, created: Created
) -> None:
    """A share of an integration with a group manager does not give the right
    to change it."""
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), admin, db_session
    )
    created.add(detail.id)
    db_session.add(Integration__User(integration_id=detail.id, user_id=scoped.id))
    db_session.commit()
    with pytest.raises(OnyxError) as error:
        admin_api.delete_integration(detail.id, scoped, db_session)
    assert error.value.status_code == 403


# Sign-in changes and connections


def _oauth_create() -> IntegrationCreate:
    return IntegrationCreate(
        for_organization=True,
        name=f"oauth-{uuid4().hex[:8]}",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=OAuthClientInput(
            provider_mode=IntegrationOAuthProviderMode.MANUAL,
            authorization_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            client_id="client-1",
            client_secret="secret-1",
        ),
        config=OpenApiConfigInput(openapi_spec=OPENAPI_SPEC),
    )


def test_client_id_change_resets_connections_and_secret_change_does_not(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    from onyx.db.integration_connection import upsert_connection__no_commit

    detail = admin_api.create_integration(_oauth_create(), admin, db_session)
    created.add(detail.id)
    upsert_connection__no_commit(
        db_session,
        integration_id=detail.id,
        user_id=member.id,
        secret=ConnectionSecret(access_token="token").model_dump(mode="json"),
        expires_at=None,
        granted_scopes=None,
    )
    db_session.commit()

    client = detail.oauth_client
    assert client is not None
    same_id = OAuthClientInput(
        **client.model_dump(exclude={"has_client_secret"}), client_secret="secret-2"
    )
    admin_api.update_integration(
        detail.id, IntegrationUpdate(oauth_client=same_id), admin, db_session
    )
    connection = get_connection(db_session, detail.id, member.id)
    assert connection is not None
    assert connection.status is IntegrationConnectionStatus.CONNECTED
    stored = get_oauth_client(db_session, detail.id)
    assert stored is not None and stored.client_secret is not None
    assert stored.client_secret.get_value(apply_mask=False) == "secret-2"

    keep_secret = OAuthClientInput(
        **client.model_dump(exclude={"has_client_secret"}),
        client_secret=None,
    )
    keep_secret.client_id = "client-2"
    admin_api.update_integration(
        detail.id, IntegrationUpdate(oauth_client=keep_secret), admin, db_session
    )
    db_session.expire_all()
    connection = get_connection(db_session, detail.id, member.id)
    assert connection is not None
    assert connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT
    stored = get_oauth_client(db_session, detail.id)
    assert stored is not None and stored.client_secret is not None
    assert stored.client_secret.get_value(apply_mask=False) == "secret-2"


def test_a_new_header_field_resets_connections_and_a_literal_change_does_not(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    request = _openapi_create()
    request.auth_mode = IntegrationAuthMode.INDIVIDUAL
    detail = admin_api.create_integration(request, admin, db_session)
    created.add(detail.id)
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    connect_with_fields__no_commit(integration, member, {"api_key": "k"}, db_session)
    db_session.commit()

    def status() -> IntegrationConnectionStatus:
        db_session.expire_all()
        connection = get_connection(db_session, detail.id, member.id)
        assert connection is not None
        return connection.status

    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(header_template={"X-Api-Key": "{api_key}", "X-Team": "a"}),
        admin,
        db_session,
    )
    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            credential_fields=[
                CredentialField(key="api_key", label="Weather key", secret=True)
            ]
        ),
        admin,
        db_session,
    )
    assert status() is IntegrationConnectionStatus.CONNECTED

    # The explicit fields leave out the new placeholder.
    updated = admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            header_template={"X-Api-Key": "{api_key}", "X-Tenant": "{tenant}"},
            credential_fields=[
                CredentialField(key="api_key", label="Weather key", secret=True)
            ],
        ),
        admin,
        db_session,
    )
    assert [field.key for field in updated.credential_fields] == ["api_key", "tenant"]
    assert status() is IntegrationConnectionStatus.NEEDS_RECONNECT


def test_an_oauth_template_cannot_use_a_placeholder_that_oauth_does_not_fill(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)

    with pytest.raises(OnyxError) as error:
        admin_api.update_integration(
            detail.id,
            IntegrationUpdate(
                auth_method=IntegrationAuthMethod.OAUTH2,
                oauth_client=_oauth_create().oauth_client,
                header_template={"X-Api-Key": "{api_key}"},
            ),
            admin,
            db_session,
        )
    assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
    db_session.rollback()

    updated = admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            auth_method=IntegrationAuthMethod.OAUTH2,
            oauth_client=_oauth_create().oauth_client,
            header_template={"Authorization": "Bearer {access_token}"},
        ),
        admin,
        db_session,
    )
    assert updated.header_template == {"Authorization": "Bearer {access_token}"}


def test_a_switch_to_oauth_drops_the_api_key_template_and_fields(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    oauth_client = _oauth_create().oauth_client

    updated = admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            auth_method=IntegrationAuthMethod.OAUTH2, oauth_client=oauth_client
        ),
        admin,
        db_session,
    )

    assert updated.header_template is None
    assert updated.credential_fields == []
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    db_session.refresh(integration)
    assert integration.header_template is None
    assert integration.credential_fields is None


def test_scoped_owner_starts_the_organization_sign_in_of_its_integration(
    db_session: Session, scoped: User, member: User, created: Created
) -> None:
    """A scoped manage:actions holder signs in for the organization on an
    integration in its "My uploads"; another member cannot."""
    request = _oauth_create()
    request.for_organization = False
    request.auth_mode = IntegrationAuthMode.SHARED
    detail = admin_api.create_integration(request, scoped, db_session)
    created.add(detail.id)
    integration = db_session.get(Integration, detail.id)
    assert integration is not None

    url = start_integration_oauth(integration, scoped, db_session)
    assert url.startswith("https://auth.example.com/authorize")

    with pytest.raises(OnyxError) as error:
        start_integration_oauth(integration, member, db_session)
    assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_per_user_key_mcp_without_a_template_needs_setup(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    """A migrated per-user API key MCP server whose template did not read has
    no fields for new users to fill, so the admin list shows it as not ready.
    The status of a user does not change."""
    integration, _ = make_mcp_integration(
        db_session,
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.API_KEY,
    )
    created.add(integration.id)

    view = admin_api.get_integration_admin(integration.id, admin, db_session)
    assert view.needs_setup is True
    assert view.setup_reason == "Add the header template."
    assert (
        integration_status(integration, member, db_session).state
        is not ConnectionState.NOT_SET_UP
    )

    integration.header_template = {"X-Api-Key": "{api_key}"}
    db_session.commit()
    view = admin_api.get_integration_admin(integration.id, admin, db_session)
    assert view.needs_setup is False


def test_organization_connection_put_and_delete(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    status = admin_api.save_organization_connection(
        detail.id, ConnectionFieldsRequest(fields={"api_key": "k"}), admin, db_session
    )
    assert status.state.value == "connected"
    assert (
        admin_api.get_integration_admin(detail.id, admin, db_session).needs_setup
        is False
    )
    status = admin_api.delete_organization_connection(detail.id, admin, db_session)
    assert status.state.value == "not_set_up"
    assert status.reason == "Connect the account of the organization."
    view = admin_api.get_integration_admin(detail.id, admin, db_session)
    assert view.organization_status is not None
    assert view.organization_status.reason == "Connect the account of the organization."
    assert view.setup_reason == view.organization_status.reason


def test_admin_view_tells_the_admin_to_reconnect_after_a_sign_in_change(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    admin_api.save_organization_connection(
        detail.id, ConnectionFieldsRequest(fields={"api_key": "k"}), admin, db_session
    )
    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            header_template={"X-Api-Key": "{api_key}", "X-Tenant": "{tenant}"}
        ),
        admin,
        db_session,
    )

    view = admin_api.get_integration_admin(detail.id, admin, db_session)
    assert view.organization_status is not None
    assert view.organization_status.state.value == "needs_reconnect"
    assert view.organization_status.reason == (
        "The sign-in settings changed. Connect the account of the organization again."
    )
    member_view = api.get_integration_for_member(detail.id, member, db_session)
    assert member_view.status.reason == "Your admin changed the sign-in settings"


def test_a_masked_connection_value_is_refused(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    secret = "real-organization-key-123"
    admin_api.save_organization_connection(
        detail.id,
        ConnectionFieldsRequest(fields={"api_key": secret}),
        admin,
        db_session,
    )
    with pytest.raises(OnyxError) as error:
        admin_api.save_organization_connection(
            detail.id,
            ConnectionFieldsRequest(fields={"api_key": mask_string(secret)}),
            admin,
            db_session,
        )
    assert error.value.status_code == 400
    db_session.rollback()
    connection = get_connection(db_session, detail.id, None)
    assert connection is not None
    assert read_connection_secret(connection).fields == {"api_key": secret}


def test_connection_save_holds_the_integration_row_lock(
    db_session: Session, admin: User, created: Created
) -> None:
    """A settings change takes the same lock, so it cannot commit between
    the checks of the save and its write."""
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    admin_api.save_organization_connection(
        detail.id, ConnectionFieldsRequest(fields={"api_key": "k"}), admin, db_session
    )
    integration = db_session.get(Integration, detail.id)
    assert integration is not None

    connect_with_fields__no_commit(integration, None, {"api_key": "k2"}, db_session)
    try:
        with get_session_with_current_tenant() as other:
            with pytest.raises(OperationalError):
                other.execute(
                    select(Integration.id)
                    .where(Integration.id == detail.id)
                    .with_for_update(nowait=True)
                )
    finally:
        db_session.rollback()


# Actions


def test_admin_actions_get_put_and_refresh(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    actions = admin_api.get_integration_actions(detail.id, admin, db_session)
    by_key = {action.key: action for action in actions.actions}
    assert by_key["get_forecast"].default_policy.value == "allow"
    assert by_key["set_alert"].default_policy.value == "ask"

    from onyx.integrations.models import EffectivePolicy

    updated = admin_api.set_integration_actions(
        detail.id,
        IntegrationActionsUpdate(
            default_policy=EffectivePolicy.BLOCKED,
            actions={"get_forecast": EffectivePolicy.ASK},
        ),
        admin,
        db_session,
    )
    by_key = {action.key: action for action in updated.actions}
    assert updated.default_policy is EffectivePolicy.BLOCKED
    assert by_key["get_forecast"].effective_admin_policy is EffectivePolicy.ASK
    assert by_key["set_alert"].effective_admin_policy is EffectivePolicy.BLOCKED
    assert by_key["set_alert"].admin_policy is None

    refreshed = admin_api.refresh_integration_actions(detail.id, admin, db_session)
    assert {action.key for action in refreshed.actions} == {
        "get_forecast",
        "set_alert",
    }

    with pytest.raises(OnyxError):
        admin_api.set_integration_actions(
            detail.id,
            IntegrationActionsUpdate(actions={"missing": EffectivePolicy.ASK}),
            admin,
            db_session,
        )

    # A save from a stale page names only what it changed, so it keeps the
    # newer settings of the other rows, the default row too.
    admin_api.set_integration_actions(
        detail.id,
        IntegrationActionsUpdate(actions={"set_alert": EffectivePolicy.ALLOW}),
        admin,
        db_session,
    )
    stale = admin_api.set_integration_actions(
        detail.id,
        IntegrationActionsUpdate(actions={"get_forecast": EffectivePolicy.BLOCKED}),
        admin,
        db_session,
    )
    by_key = {action.key: action for action in stale.actions}
    assert stale.default_policy is EffectivePolicy.BLOCKED
    assert by_key["get_forecast"].admin_policy is EffectivePolicy.BLOCKED
    assert by_key["set_alert"].admin_policy is EffectivePolicy.ALLOW


def test_refresh_of_an_mcp_server_stores_discovered_tools(
    db_session: Session, admin: User, created: Created
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.com/mcp",
        name=f"mcp-{uuid4().hex[:8]}",
        tools=("old",),
    )
    created.add(integration.id)
    give_access(db_session, [integration])
    spec = IntegrationActionSpec(
        key="new",
        source=IntegrationActionSource.MCP,
        display_name="New",
        description=None,
        read_only=None,
        default_policy=IntegrationActionPolicyValue.ALLOW,
    )
    with patch("onyx.integrations.service.fetch_mcp_actions", return_value=[spec]):
        refreshed = admin_api.refresh_integration_actions(
            integration.id, admin, db_session
        )
    assert [action.key for action in refreshed.actions] == ["new"]


def test_refresh_refuses_actions_of_a_server_url_that_changed_meanwhile(
    db_session: Session, admin: User, created: Created
) -> None:
    integration, server = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.com/mcp",
        name=f"mcp-{uuid4().hex[:8]}",
        tools=("old",),
    )
    created.add(integration.id)
    give_access(db_session, [integration])
    server_id = server.id
    spec = IntegrationActionSpec(
        key="new",
        source=IntegrationActionSource.MCP,
        display_name="New",
        description=None,
        read_only=None,
        default_policy=IntegrationActionPolicyValue.ALLOW,
    )

    def discover_while_the_url_changes(*_: object) -> list[IntegrationActionSpec]:
        with get_session_with_current_tenant() as other_session:
            other_server = other_session.get(MCPServer, server_id)
            assert other_server is not None
            other_server.server_url = "https://other.example.com/mcp"
            other_session.commit()
        return [spec]

    with (
        patch(
            "onyx.integrations.service.fetch_mcp_actions",
            side_effect=discover_while_the_url_changes,
        ),
        pytest.raises(OnyxError) as raised,
    ):
        admin_api.refresh_integration_actions(integration.id, admin, db_session)

    assert raised.value.error_code is OnyxErrorCode.CONFLICT
    db_session.rollback()
    assert [
        action.key for action in list_integration_actions(integration.id, db_session)
    ] == ["old"]


def test_refresh_refuses_actions_of_a_header_template_that_changed_meanwhile(
    db_session: Session, admin: User, created: Created
) -> None:
    integration, _ = make_mcp_integration(
        db_session,
        name=f"mcp-{uuid4().hex[:8]}",
        tools=("old",),
        header_template={"X-Team": "blue"},
    )
    integration_id = created.add(integration.id)
    give_access(db_session, [integration])
    spec = IntegrationActionSpec(
        key="new",
        source=IntegrationActionSource.MCP,
        display_name="New",
        description=None,
        read_only=None,
        default_policy=IntegrationActionPolicyValue.ALLOW,
    )

    def discover_while_the_headers_change(*_: object) -> list[IntegrationActionSpec]:
        with get_session_with_current_tenant() as other_session:
            other = other_session.get(Integration, integration_id)
            assert other is not None
            other.header_template = {"X-Team": "red"}
            other_session.commit()
        return [spec]

    with (
        patch(
            "onyx.integrations.service.fetch_mcp_actions",
            side_effect=discover_while_the_headers_change,
        ),
        pytest.raises(OnyxError) as raised,
    ):
        admin_api.refresh_integration_actions(integration_id, admin, db_session)

    assert raised.value.error_code is OnyxErrorCode.CONFLICT
    db_session.rollback()
    assert [
        action.key for action in list_integration_actions(integration_id, db_session)
    ] == ["old"]


def _unauthorized(status: int) -> HTTPStatusError:
    request = Request("POST", "https://mcp.example.com/mcp")
    return HTTPStatusError(
        "refused", request=request, response=Response(status, request=request)
    )


@pytest.mark.parametrize(
    ("connect", "failure", "status", "detail"),
    [
        (False, None, 400, "Connect {name} first to load its actions."),
        (
            True,
            _unauthorized(401),
            400,
            "{name} refused the credential. Reconnect it and try again.",
        ),
        (
            True,
            _unauthorized(403),
            400,
            "{name} refused the credential. Reconnect it and try again.",
        ),
        (True, ConnectError("refused"), 502, "Could not reach {name}."),
    ],
)
def test_refresh_of_an_individual_mcp_server_uses_the_admin_connection(
    db_session: Session,
    admin: User,
    created: Created,
    connect: bool,
    failure: Exception | None,
    status: int,
    detail: str,
) -> None:
    name = f"mcp-{uuid4().hex[:8]}"
    with patch(
        "onyx.integrations.kinds.mcp_server.discover_mcp_tools",
        side_effect=AssertionError("Create does not discover"),
    ):
        integration = admin_api.create_integration(
            IntegrationCreate(
                name=name,
                auth_mode=IntegrationAuthMode.INDIVIDUAL,
                auth_method=IntegrationAuthMethod.API_KEY,
                header_template={"Authorization": "Bearer {api_key}"},
                config=McpServerConfigInput(server_url="https://mcp.example.com/mcp"),
            ),
            admin,
            db_session,
        )
    created.add(integration.id)
    if connect:
        api.save_member_connection(
            integration.id,
            ConnectionFieldsRequest(fields={"api_key": "admin-key"}),
            admin,
            db_session,
        )

    with (
        patch(
            "onyx.integrations.kinds.mcp_server.discover_mcp_tools",
            side_effect=failure,
        ) as discover,
        pytest.raises(OnyxError) as error,
    ):
        admin_api.refresh_integration_actions(integration.id, admin, db_session)

    assert error.value.status_code == status
    assert error.value.detail == detail.format(name=name)
    if connect:
        assert discover.call_args.args[1] == {"Authorization": "Bearer admin-key"}
    else:
        discover.assert_not_called()


def test_member_connect_refuses_a_key_that_the_mcp_server_rejects(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    with patch(
        "onyx.integrations.kinds.mcp_server.discover_mcp_tools", return_value=[]
    ):
        integration = admin_api.create_integration(
            IntegrationCreate(
                for_organization=True,
                name=f"mcp-{uuid4().hex[:8]}",
                auth_mode=IntegrationAuthMode.INDIVIDUAL,
                auth_method=IntegrationAuthMethod.API_KEY,
                header_template={
                    "Authorization": "Bearer {api_key}",
                    "X-User": "{user_email}",
                },
                config=McpServerConfigInput(server_url="https://mcp.example.com/mcp"),
            ),
            admin,
            db_session,
        )
    created.add(integration.id)

    with (
        patch(
            "onyx.integrations.kinds.mcp_server.discover_mcp_tools",
            side_effect=_unauthorized(401),
        ) as discover,
        pytest.raises(OnyxError) as error,
    ):
        api.save_member_connection(
            integration.id,
            ConnectionFieldsRequest(fields={"api_key": "wrong-key"}),
            member,
            db_session,
        )
    assert error.value.error_code is OnyxErrorCode.CREDENTIAL_INVALID
    assert discover.call_args.args[1] == {
        "Authorization": "Bearer wrong-key",
        "X-User": member.email,
    }
    db_session.rollback()

    with patch(
        "onyx.integrations.kinds.mcp_server.discover_mcp_tools", return_value=[]
    ):
        status = api.save_member_connection(
            integration.id,
            ConnectionFieldsRequest(fields={"api_key": "right-key"}),
            member,
            db_session,
        )
    assert status.state is ConnectionState.CONNECTED


# Member


def test_member_cannot_save_always_allow_over_an_admin_block_or_allow(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    from onyx.integrations.models import EffectivePolicy

    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    admin_api.set_integration_actions(
        detail.id,
        IntegrationActionsUpdate(actions={"set_alert": EffectivePolicy.BLOCKED}),
        admin,
        db_session,
    )

    for key in ("set_alert", "get_forecast"):
        with pytest.raises(OnyxError) as error:
            api.save_action_grants(
                detail.id,
                ActionGrantsUpdate(actions={key: "allow"}),
                member,
                db_session,
            )
        assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
        assert key in error.value.detail
    assert all(
        action.user_policy is None
        for action in api.get_action_grants(detail.id, member, db_session).actions
    )


@pytest.mark.usefixtures("craft_available")
def test_member_cannot_save_always_allow_for_an_action_that_always_asks(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    request = _custom_create()
    request.for_organization = True
    detail = admin_api.create_integration(request, admin, db_session)
    created.add(detail.id)

    with pytest.raises(OnyxError) as error:
        api.save_action_grants(
            detail.id,
            ActionGrantsUpdate(actions={WHOLE_DOMAIN_ACTION_TYPE: "allow"}),
            member,
            db_session,
        )
    assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert all(
        action.user_policy is None
        for action in api.get_action_grants(detail.id, member, db_session).actions
    )


@pytest.mark.usefixtures("craft_available")
def test_member_list_carries_the_craft_fields(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    request = _custom_create()
    request.for_organization = True
    custom = admin_api.create_integration(request, admin, db_session)
    created.add(custom.id)
    with patch("onyx.integrations.service.discover_mcp_tools", return_value=[]):
        mcp = admin_api.create_integration(
            IntegrationCreate(
                for_organization=True,
                name=f"mcp-{uuid4().hex[:8]}",
                auth_mode=IntegrationAuthMode.NONE,
                config=McpServerConfigInput(server_url="https://mcp.example.com/mcp"),
            ),
            admin,
            db_session,
        )
    created.add(mcp.id)
    api.save_member_connection(
        custom.id,
        ConnectionFieldsRequest(fields={"token": "secret-value"}),
        member,
        db_session,
    )

    listed = {
        view.id: view for view in api.list_integrations_for_member(member, db_session)
    }
    app = get_external_app_for_integration(custom.id, db_session)
    assert app is not None
    custom_view = listed[custom.id]
    assert custom_view.external_app_id == app.id
    assert custom_view.service_urls == ["https://api.custom.example.com"]
    assert set(custom_view.credential_values) == {"token"}
    assert custom_view.credential_values["token"] != "secret-value"
    assert (custom_view.mcp_server_id, custom_view.server_url) == (None, None)
    server = get_mcp_server_for_integration(mcp.id, db_session)
    assert server is not None
    mcp_view = listed[mcp.id]
    assert (mcp_view.mcp_server_id, mcp_view.server_url) == (
        server.id,
        "https://mcp.example.com/mcp",
    )
    assert mcp_view.external_app_id is None


def test_member_cannot_reach_a_private_integration(
    db_session: Session, scoped: User, member: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), scoped, db_session
    )
    created.add(detail.id)
    with pytest.raises(OnyxError) as error:
        api.get_integration_for_member(detail.id, member, db_session)
    assert error.value.status_code == 404


def test_agent_catalog_lists_the_integrations_the_user_has_access_to(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    options = {
        option.id: option for option in api.get_agent_catalog(member, db_session)
    }
    assert options[detail.id].name == detail.name
    assert len(options[detail.id].actions) == 2
    assert options[detail.id].users_can_save_always_allow


# Agents


def _persona(
    db_session: Session,
    user: User,
    *,
    tool_ids: list[int] | None,
    integration_links: list[PersonaIntegrationLink] | None,
    persona_id: int | None = None,
) -> int:
    persona = upsert_persona(
        user=user,
        name=f"agent-{uuid4().hex[:8]}" if persona_id is None else "agent-edit",
        description="",
        starter_messages=None,
        system_prompt="",
        task_prompt="",
        datetime_aware=True,
        is_public=True,
        db_session=db_session,
        tool_ids=tool_ids,
        integration_links=integration_links,
        persona_id=persona_id,
    )
    return persona.id


def _links(db_session: Session, persona_id: int) -> dict[int, dict[str, Any]]:
    return {
        link.integration_id: link.action_settings
        for link in list_persona_integration_links(db_session, persona_id)
    }


def test_persona_integrations_and_legacy_tool_ids(
    db_session: Session, admin: User, created: Created
) -> None:
    openapi = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(openapi.id)
    openapi_tool = get_openapi_tool_for_integration(openapi.id, db_session)
    assert openapi_tool is not None
    mcp, server = make_mcp_integration(
        db_session,
        server_url="https://mcp.example.com/mcp",
        name=f"mcp-{uuid4().hex[:8]}",
        tools=("hello", "bye"),
    )
    created.add(mcp.id)
    give_access(db_session, [mcp])
    old_mcp_tool = _old_mcp_tool(db_session, server.id, "hello")

    persona_id = _persona(
        db_session,
        admin,
        tool_ids=[openapi_tool.id, old_mcp_tool.id],
        integration_links=None,
    )
    assert _links(db_session, persona_id) == {
        openapi.id: {},
        mcp.id: {"default": "blocked", "actions": {"hello": "inherit"}},
    }
    snapshot = persona_api.get_persona(persona_id, admin, db_session)
    assert [
        (link.integration_id, link.integration_name) for link in snapshot.integrations
    ] == sorted(
        [(openapi.id, openapi.name), (mcp.id, mcp.name)], key=lambda link: link[1]
    )

    # Old tool ids with no MCP tool remove the link of the old MCP tool.
    _persona(
        db_session, admin, tool_ids=[], integration_links=None, persona_id=persona_id
    )
    assert _links(db_session, persona_id) == {}


def _old_mcp_tool(db_session: Session, server_id: int, name: str) -> Tool:
    tool = Tool(
        name=name,
        description="",
        mcp_server_id=server_id,
        enabled=True,
        passthrough_auth=False,
    )
    db_session.add(tool)
    db_session.commit()
    return tool


def test_legacy_tool_ids_of_two_servers_give_one_link_for_each_server(
    db_session: Session, admin: User, created: Created
) -> None:
    """A tool name that the request did not select on a server stays blocked
    on that server, also when the request selects it on another server."""
    first, first_server = make_mcp_integration(
        db_session, name=f"mcp-{uuid4().hex[:8]}", tools=("alpha", "beta")
    )
    second, second_server = make_mcp_integration(
        db_session, name=f"mcp-{uuid4().hex[:8]}", tools=("beta",)
    )
    created.add(first.id)
    created.add(second.id)
    give_access(db_session, [first, second])
    alpha = _old_mcp_tool(db_session, first_server.id, "alpha")
    beta = _old_mcp_tool(db_session, second_server.id, "beta")

    persona_id = _persona(
        db_session, admin, tool_ids=[alpha.id, beta.id], integration_links=None
    )

    assert _links(db_session, persona_id) == {
        first.id: {"default": "blocked", "actions": {"alpha": "inherit"}},
        second.id: {"default": "blocked", "actions": {"beta": "inherit"}},
    }


def test_an_agent_link_needs_access_to_the_integration(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    """An editor adds only an integration that the editor has access to. A
    link that the agent has stays when an editor with no access saves old
    tool ids."""
    mcp, server = make_mcp_integration(
        db_session, name=f"mcp-{uuid4().hex[:8]}", tools=("hello",)
    )
    created.add(mcp.id)
    give_access(db_session, [mcp], published=False, owner_user_id=admin.id)
    hello = _old_mcp_tool(db_session, server.id, "hello")
    link = PersonaIntegrationLink(integration_id=mcp.id)

    with pytest.raises(ValueError, match="do not have access"):
        _persona(db_session, member, tool_ids=None, integration_links=[link])
    db_session.rollback()

    persona_id = _persona(db_session, admin, tool_ids=None, integration_links=[link])
    persona = db_session.get(Persona, persona_id)
    assert persona is not None
    persona.user_id = member.id
    db_session.commit()

    _persona(
        db_session,
        member,
        tool_ids=[hello.id],
        integration_links=None,
        persona_id=persona_id,
    )

    assert _links(db_session, persona_id) == {mcp.id: {}}
    # The agent gives the editor no access to the integration.
    assert api.get_agent_integration_ids(persona_id, member, db_session) == []
    assert api.get_agent_integration_ids(persona_id, admin, db_session) == [mcp.id]


# Review fixes


def _member_connection(db_session: Session, integration_id: int, user: User) -> None:
    from onyx.db.integration_connection import upsert_connection__no_commit

    upsert_connection__no_commit(
        db_session,
        integration_id=integration_id,
        user_id=user.id,
        secret=ConnectionSecret(access_token="token").model_dump(mode="json"),
        expires_at=None,
        granted_scopes=None,
    )
    db_session.commit()


def _connection_status(
    db_session: Session, integration_id: int, user: User
) -> IntegrationConnectionStatus:
    db_session.expire_all()
    connection = get_connection(db_session, integration_id, user.id)
    assert connection is not None
    return connection.status


@pytest.mark.usefixtures("craft_available")
@pytest.mark.parametrize("shape", ["openapi", "custom"])
def test_a_destination_change_resets_connections(
    db_session: Session, admin: User, member: User, created: Created, shape: str
) -> None:
    request = _openapi_create() if shape == "openapi" else _custom_create()
    detail = admin_api.create_integration(request, admin, db_session)
    created.add(detail.id)
    _member_connection(db_session, detail.id, member)

    admin_api.update_integration(
        detail.id, IntegrationUpdate(name="Renamed"), admin, db_session
    )
    assert (
        _connection_status(db_session, detail.id, member)
        is IntegrationConnectionStatus.CONNECTED
    )
    if shape == "openapi":
        tool = get_openapi_tool_for_integration(detail.id, db_session)
        assert tool is not None
        assert (tool.name, tool.display_name) == ("Renamed", "Renamed")
    else:
        app = get_external_app_for_integration(detail.id, db_session)
        assert app is not None and app.name == "Renamed"

    config = (
        OpenApiConfigInput(
            openapi_spec={
                **OPENAPI_SPEC,
                "servers": [{"url": "https://new.example.com"}],
                "paths": {
                    "/forecast": {
                        "get": {
                            "operationId": "get_forecast",
                            "summary": "Get the forecast",
                        }
                    }
                },
            }
        )
        if shape == "openapi"
        else CustomConfigInput(upstream_url_patterns=["https://new.example.com/*"])
    )
    admin_api.update_integration(
        detail.id, IntegrationUpdate(config=config), admin, db_session
    )
    assert (
        _connection_status(db_session, detail.id, member)
        is IntegrationConnectionStatus.NEEDS_RECONNECT
    )
    if shape == "openapi":
        assert [a.key for a in list_integration_actions(detail.id, db_session)] == [
            "get_forecast"
        ]


def test_scoped_owner_cannot_move_an_onyx_login_integration(
    db_session: Session, scoped: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), scoped, db_session
    )
    created.add(detail.id)
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    integration.auth_mode = IntegrationAuthMode.INDIVIDUAL
    integration.auth_method = IntegrationAuthMethod.ONYX_LOGIN
    integration.header_template = {"Authorization": "Bearer {access_token}"}
    db_session.commit()

    for update in (
        IntegrationUpdate(
            config=OpenApiConfigInput(
                openapi_spec={
                    **OPENAPI_SPEC,
                    "servers": [{"url": "https://other.example.com"}],
                }
            )
        ),
        IntegrationUpdate(header_template={"Authorization": "Bearer {access_token}"}),
    ):
        with pytest.raises(OnyxError) as error:
            admin_api.update_integration(detail.id, update, scoped, db_session)
        assert error.value.error_code is OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        db_session.rollback()


def test_saving_a_legacy_oauth_client_keeps_its_credentials(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    from onyx.db.enums import IntegrationLegacyFormat
    from onyx.integrations.connection_models import read_oauth_client

    detail = admin_api.create_integration(_oauth_create(), admin, db_session)
    created.add(detail.id)
    stored = get_oauth_client(db_session, detail.id)
    assert stored is not None
    stored.legacy_format = IntegrationLegacyFormat.MCP_CONFIG.value
    stored.client_id = None
    stored.client_secret = None
    stored.registration = {  # ty: ignore[invalid-assignment]
        "client_info": {"client_id": "legacy-id", "client_secret": "legacy-secret"}
    }
    db_session.commit()
    _member_connection(db_session, detail.id, member)

    view = admin_api.get_integration_admin(detail.id, admin, db_session)
    assert view.oauth_client is not None
    assert view.oauth_client.client_id == "legacy-id"
    assert view.oauth_client.has_client_secret is True

    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            oauth_client=OAuthClientInput(
                **view.oauth_client.model_dump(exclude={"has_client_secret"})
            )
        ),
        admin,
        db_session,
    )

    assert (
        _connection_status(db_session, detail.id, member)
        is IntegrationConnectionStatus.CONNECTED
    )
    stored = get_oauth_client(db_session, detail.id)
    assert stored is not None and stored.legacy_format is None
    credentials = read_oauth_client(stored)
    assert credentials.client_id == "legacy-id"
    assert credentials.client_secret == "legacy-secret"


def test_turning_default_chat_off_makes_the_plugin_available(
    db_session: Session, admin: User, created: Created
) -> None:

    snapshot = tool_api.create_custom_tool(
        CustomToolCreate(
            name=f"chat-{uuid4().hex[:8]}",
            description="Chat",
            definition=OPENAPI_SPEC,
            custom_headers=[],
            passthrough_auth=False,
        ),
        db_session,
        admin,
    )
    integration = get_integration_by_kind_row(
        Integration.tool_id, snapshot.id, db_session
    )
    assert integration is not None
    created.add(integration.id)

    for enabled, policy in (
        (True, PluginInstallationPolicy.DEFAULT),
        (False, PluginInstallationPolicy.AVAILABLE),
    ):
        updated = tool_api.update_custom_tool(
            snapshot.id,
            CustomToolUpdate(default_chat_enabled=enabled),
            db_session,
            admin,
        )
        assert updated.default_chat_enabled is enabled
        db_session.refresh(integration)
        assert integration.installation_policy is policy


def _linear_create() -> IntegrationCreate:
    return IntegrationCreate(
        for_organization=True,
        name=f"linear-{uuid4().hex[:8]}",
        auth_mode=IntegrationAuthMode.INDIVIDUAL,
        auth_method=IntegrationAuthMethod.OAUTH2,
        oauth_client=OAuthClientInput(
            provider_mode=IntegrationOAuthProviderMode.PRESET
        ),
        config=PresetConfigInput(
            preset_id="LINEAR",
            organization_credentials={"client_id": "lin-id", "client_secret": "lin-s"},
        ),
    )


@pytest.mark.usefixtures("craft_available")
def test_cloud_protects_onyx_managed_presets(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_linear_create(), admin, db_session)
    created.add(detail.id)
    assert detail.can_delete is True

    linear = _linear_create().config
    assert isinstance(linear, PresetConfigInput)
    assert linear.preset_id in {
        preset.id for preset in admin_api.list_integration_presets(admin)
    }
    with patch("onyx.integrations.service.MULTI_TENANT", True):
        assert linear.preset_id not in {
            preset.id for preset in admin_api.list_integration_presets(admin)
        }
        with pytest.raises(OnyxError) as error:
            admin_api.create_integration(_linear_create(), admin, db_session)
        assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
        db_session.rollback()

        view = admin_api.get_integration_admin(detail.id, admin, db_session)
        assert view.oauth_client is None
        assert view.can_delete is False

        with pytest.raises(OnyxError) as error:
            admin_api.update_integration(
                detail.id,
                IntegrationUpdate(
                    oauth_client=OAuthClientInput(
                        provider_mode=IntegrationOAuthProviderMode.PRESET,
                        client_id="other",
                    )
                ),
                admin,
                db_session,
            )
        assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
        db_session.rollback()

        renamed = admin_api.update_integration(
            detail.id, IntegrationUpdate(name="Linear"), admin, db_session
        )
        assert renamed.name == "Linear"

        with pytest.raises(OnyxError) as error:
            admin_api.delete_integration(detail.id, admin, db_session)
        assert error.value.error_code is OnyxErrorCode.INVALID_INPUT
        db_session.rollback()


def test_a_member_row_carries_the_install_setting_for_the_user(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    from onyx.db.models import Integration__UserGroup, User__UserGroup, UserGroup

    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    group = UserGroup(name=f"u6-required-{uuid4().hex[:8]}")
    db_session.add(group)
    db_session.flush()
    db_session.add(User__UserGroup(user_id=member.id, user_group_id=group.id))
    db_session.add(
        Integration__UserGroup(
            integration_id=detail.id,
            user_group_id=group.id,
            permission=None,
            installation_policy=PluginInstallationPolicy.REQUIRED,
        )
    )
    db_session.commit()
    try:
        listed = {
            view.id: view
            for view in api.list_integrations_for_member(member, db_session)
        }
        assert listed[detail.id].access.installation_policy is (
            PluginInstallationPolicy.REQUIRED
        )
        assert listed[detail.id].access.user_enabled is True
        member_view = api.get_integration_for_member(detail.id, member, db_session)
        assert member_view.access.installation_policy is (
            PluginInstallationPolicy.REQUIRED
        )
    finally:
        db_session.delete(group)
        db_session.commit()


# Saved header secrets


def test_literal_header_values_are_masked_and_kept_on_save(
    db_session: Session, scoped: User, created: Created
) -> None:
    secret = "static-secret-value-123"
    request = _openapi_create(for_organization=False)
    request.header_template = {"X-Api-Key": "{api_key}", "X-Static": secret}
    detail = admin_api.create_integration(request, scoped, db_session)
    created.add(detail.id)
    assert detail.header_template is not None
    masked = detail.header_template["X-Static"]
    assert masked != secret
    assert detail.header_template["X-Api-Key"] == "{api_key}"

    updated = admin_api.update_integration(
        detail.id,
        IntegrationUpdate(
            header_template={"X-Api-Key": "{api_key}", "X-Static": masked}
        ),
        scoped,
        db_session,
    )
    assert updated.header_template == detail.header_template
    integration = db_session.get(Integration, detail.id)
    assert integration is not None
    db_session.refresh(integration)
    assert integration.header_template == {"X-Api-Key": "{api_key}", "X-Static": secret}

    with pytest.raises(OnyxError) as error:
        admin_api.update_integration(
            detail.id,
            IntegrationUpdate(header_template={"X-Other": masked}),
            scoped,
            db_session,
        )
    assert error.value.status_code == 400

    # A reader that cannot manage the integration gets no header values.
    _make_available(db_session, detail.id)
    view = admin_api.get_integration_admin(detail.id, scoped, db_session)
    assert view.can_manage is False
    assert view.header_template is None


def test_custom_tool_alias_reads_and_keeps_migrated_headers(
    db_session: Session, admin: User, created: Created
) -> None:
    """A migrated API key tool keeps its headers on the organization
    connection in the old format and has no header template."""
    snapshot = tool_api.create_custom_tool(
        CustomToolCreate(
            name=f"migrated-{uuid4().hex[:8]}",
            description="Migrated",
            definition=OPENAPI_SPEC,
            custom_headers=[],
            passthrough_auth=False,
        ),
        db_session,
        admin,
    )
    integration = get_integration_by_kind_row(
        Integration.tool_id, snapshot.id, db_session
    )
    assert integration is not None
    created.add(integration.id)
    integration.auth_mode = IntegrationAuthMode.SHARED
    integration.auth_method = IntegrationAuthMethod.API_KEY
    db_session.execute(
        text(
            "INSERT INTO integration_connection "
            "(integration_id, user_id, secret, legacy_format, status) "
            "VALUES (:integration_id, NULL, convert_to(:headers, 'UTF8'), "
            "'tool_headers', 'connected')"
        ),
        {
            "integration_id": integration.id,
            "headers": json.dumps([{"key": "X-Api-Key", "value": "abc{1}-secret"}]),
        },
    )
    db_session.commit()

    fetched = tool_api.get_custom_tool(snapshot.id, db_session, admin)
    assert fetched.custom_headers is not None
    assert [header["key"] for header in fetched.custom_headers] == ["X-Api-Key"]
    masked = fetched.custom_headers[0]["value"]
    assert masked != "abc{1}-secret"

    tool_api.update_custom_tool(
        snapshot.id,
        CustomToolUpdate(custom_headers=[Header(key="X-Api-Key", value=masked)]),
        db_session,
        admin,
    )
    db_session.expire_all()
    connection = get_connection(db_session, integration.id, None)
    assert connection is not None
    assert read_connection_secret(connection).fields == {"X-Api-Key": "abc{1}-secret"}


def test_custom_tool_alias_keeps_a_passthrough_header_with_braces(
    db_session: Session, admin: User, created: Created
) -> None:
    snapshot = tool_api.create_custom_tool(
        CustomToolCreate(
            name=f"passthrough-{uuid4().hex[:8]}",
            description="Passthrough",
            definition=OPENAPI_SPEC,
            custom_headers=[Header(key="X-Meta", value='{"team":"blue"}')],
            passthrough_auth=True,
        ),
        db_session,
        admin,
    )
    integration = get_integration_by_kind_row(
        Integration.tool_id, snapshot.id, db_session
    )
    assert integration is not None
    created.add(integration.id)

    fetched = tool_api.get_custom_tool(snapshot.id, db_session, admin)
    assert fetched.custom_headers is not None
    assert [header["key"] for header in fetched.custom_headers] == ["X-Meta"]
    tool_api.update_custom_tool(
        snapshot.id,
        CustomToolUpdate(
            custom_headers=[Header(**header) for header in fetched.custom_headers],
            passthrough_auth=True,
        ),
        db_session,
        admin,
    )
    db_session.expire_all()
    assert integration.header_template is not None
    assert integration.header_template["X-Meta"] == '{{"team":"blue"}}'


def test_custom_tool_alias_save_keeps_oauth_sign_in(
    db_session: Session, admin: User, created: Created
) -> None:
    snapshot = tool_api.create_custom_tool(
        CustomToolCreate(
            name=f"oauth-{uuid4().hex[:8]}",
            description="OAuth",
            definition=OPENAPI_SPEC,
            custom_headers=[Header(key="X-Team", value="blue")],
            passthrough_auth=False,
        ),
        db_session,
        admin,
    )
    integration = get_integration_by_kind_row(
        Integration.tool_id, snapshot.id, db_session
    )
    assert integration is not None
    created.add(integration.id)
    integration.auth_mode = IntegrationAuthMode.SHARED
    integration.auth_method = IntegrationAuthMethod.OAUTH2
    integration.header_template = {
        "Authorization": "Bearer {access_token}",
        "X-Team": "blue",
    }
    db_session.add(
        IntegrationOAuthClient(
            integration_id=integration.id,
            provider_mode=IntegrationOAuthProviderMode.MANUAL,
            authorization_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            client_id="client-id",
        )
    )
    db_session.commit()

    fetched = tool_api.get_custom_tool(snapshot.id, db_session, admin)
    assert fetched.custom_headers is not None
    tool_api.update_custom_tool(
        snapshot.id,
        CustomToolUpdate(
            name="Renamed",
            custom_headers=[Header(**header) for header in fetched.custom_headers],
            passthrough_auth=fetched.passthrough_auth,
        ),
        db_session,
        admin,
    )
    db_session.expire_all()
    kept = db_session.get(Integration, integration.id)
    assert kept is not None
    assert kept.name == "Renamed"
    assert kept.auth_method is IntegrationAuthMethod.OAUTH2
    assert get_oauth_client(db_session, integration.id) is not None

    with pytest.raises(OnyxError) as exc:
        tool_api.update_custom_tool(
            snapshot.id,
            CustomToolUpdate(custom_headers=[Header(key="X-Team", value="red")]),
            db_session,
            admin,
        )
    assert exc.value.error_code is OnyxErrorCode.INVALID_INPUT
