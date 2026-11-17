"""The integration API, called through its route functions against the
database: create of each kind, the permission rules, sign-in changes, the
actions, the member choices, the agent plugins and the public tool aliases."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationOAuthProviderMode,
    MarketplaceKind,
    PluginPublishingPolicy,
)
from onyx.db.integration import (
    get_external_app_for_integration,
    get_integration_by_kind_row,
    get_mcp_server_for_integration,
    get_openapi_tool_for_integration,
    list_integration_actions,
)
from onyx.db.integration_connection import get_connection, get_oauth_client
from onyx.db.integration_policy import list_persona_plugin_links
from onyx.db.models import (
    ExternalApp,
    Integration,
    Marketplace,
    MCPServer,
    Plugin,
    Plugin__Integration,
    Tool,
    User,
)
from onyx.db.persona import upsert_persona
from onyx.db.plugin import (
    lock_plugin,
    publish_or_request_review__no_commit,
    set_plugin_preferences__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.connection_models import ConnectionSecret
from onyx.integrations.models import (
    ActionSettings,
    IntegrationActionSpec,
    LinkValue,
    PersonaPluginLink,
)
from onyx.integrations.oauth import start_integration_oauth
from onyx.server.features.integrations import admin_api, api
from onyx.server.features.integrations.models import (
    ActionGrantsUpdate,
    ConnectionFieldsRequest,
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
from onyx.server.features.persona.models import FullPersonaSnapshot
from onyx.server.features.tool import api as tool_api
from onyx.server.features.tool.models import (
    CustomToolCreate,
    CustomToolUpdate,
    Header,
    ToolSnapshot,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    hold_in_plugin,
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


def _plugin_of(db_session: Session, integration_id: int) -> Plugin:
    return db_session.scalars(
        select(Plugin)
        .join(Plugin__Integration, Plugin__Integration.plugin_id == Plugin.id)
        .where(Plugin__Integration.integration_id == integration_id)
    ).one()


def _marketplace_kind(db_session: Session, plugin: Plugin) -> MarketplaceKind:
    return db_session.scalars(
        select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
    ).one()


# Create


def test_create_openapi_makes_integration_tool_plugin_and_actions(
    db_session: Session, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)

    assert detail.kind.value == "api"
    assert detail.shape is IntegrationShape.OPENAPI
    assert detail.credential_fields[0].key == "api_key"
    assert detail.needs_setup is True
    assert detail.can_manage is True
    tool = get_openapi_tool_for_integration(detail.id, db_session)
    assert tool is not None and tool.openapi_schema == OPENAPI_SPEC
    plugin = _plugin_of(db_session, detail.id)
    assert _marketplace_kind(db_session, plugin) is MarketplaceKind.ORGANIZATION_LIBRARY
    assert plugin.published_version_id == plugin.current_version_id
    assert [ref.scope for ref in detail.plugins] == ["organization"]
    actions = {
        action.key: action for action in list_integration_actions(detail.id, db_session)
    }
    assert set(actions) == {"get_forecast", "set_alert"}
    assert detail.action_count == 2


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
    spec = IntegrationActionSpec(
        key="search",
        source=IntegrationActionSource.MCP,
        display_name="Search",
        description=None,
        read_only=True,
        default_policy=IntegrationActionPolicyValue.ALLOW,
    )
    with patch(
        "onyx.integrations.service.fetch_mcp_actions", return_value=[spec]
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
    assert detail.kind.value == "mcp_server"
    server = get_mcp_server_for_integration(detail.id, db_session)
    assert server is not None and server.server_url == "https://mcp.example.com/mcp"
    assert [a.key for a in list_integration_actions(detail.id, db_session)] == [
        "search"
    ]
    plugin = _plugin_of(db_session, detail.id)
    assert _marketplace_kind(db_session, plugin) is MarketplaceKind.USER_UPLOADS
    assert plugin.author_user_id == scoped.id
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
    assert [ref.scope for ref in detail.plugins] == ["personal"]
    assert detail.config.shape is IntegrationShape.CUSTOM


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


def test_create_rolls_back_when_a_step_fails(db_session: Session, admin: User) -> None:
    name = f"rollback-{uuid4().hex[:8]}"
    with (
        patch(
            "onyx.integrations.service.create_integration_plugin__no_commit",
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
def test_delete_removes_the_kind_row_and_the_emptied_plugin(
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
    plugin_id = _plugin_of(db_session, detail.id).id

    admin_api.delete_integration(detail.id, admin, db_session)

    db_session.expire_all()
    assert db_session.get(Integration, detail.id) is None
    assert db_session.get(kind_row[0], kind_row[1]) is None
    assert db_session.get(Plugin, plugin_id) is None


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
    plugin = _plugin_of(db_session, detail.id)
    publish_or_request_review__no_commit(
        plugin, None, plugin.current_version_id, None, "rename", db_session
    )
    db_session.commit()

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
    """A plugin in the scope of a group manager (here: shared with it) does
    not give the right to change its integration."""
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), admin, db_session
    )
    created.add(detail.id)
    plugin = _plugin_of(db_session, detail.id)
    from onyx.db.models import Plugin__User

    db_session.add(Plugin__User(plugin_id=plugin.id, user_id=scoped.id))
    db_session.commit()
    with pytest.raises(OnyxError) as error:
        admin_api.delete_integration(detail.id, scoped, db_session)
    assert error.value.status_code == 403


def test_publishing_a_plugin_with_an_integration_needs_global_manager(
    db_session: Session, scoped: User, admin: User, created: Created
) -> None:
    detail = admin_api.create_integration(
        _openapi_create(for_organization=False), scoped, db_session
    )
    created.add(detail.id)
    plugin = lock_plugin(_plugin_of(db_session, detail.id).id, db_session)
    assert plugin is not None
    with (
        patch(
            "onyx.db.plugin.load_settings",
            return_value=type(
                "S", (), {"plugin_publishing": PluginPublishingPolicy.OPEN}
            )(),
        ),
        pytest.raises(OnyxError) as error,
    ):
        publish_or_request_review__no_commit(
            plugin, None, plugin.current_version_id, scoped, "raise", db_session
        )
    assert error.value.status_code == 403
    db_session.rollback()

    plugin = lock_plugin(plugin.id, db_session)
    assert plugin is not None
    with pytest.raises(OnyxError):
        publish_or_request_review__no_commit(
            plugin,
            None,
            plugin.current_version_id,
            None,
            "raise",
            db_session,
            approver=scoped,
        )
    db_session.rollback()
    plugin = lock_plugin(plugin.id, db_session)
    assert plugin is not None
    publish_or_request_review__no_commit(
        plugin,
        None,
        plugin.current_version_id,
        None,
        "raise",
        db_session,
        approver=admin,
    )
    db_session.commit()
    assert plugin.published_version_id == plugin.current_version_id


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
    hold_in_plugin(db_session, [integration])
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


# Member


def test_member_list_detail_connection_and_grants(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    request = _openapi_create()
    request.auth_mode = IntegrationAuthMode.INDIVIDUAL
    detail = admin_api.create_integration(request, admin, db_session)
    created.add(detail.id)

    listed = {
        view.id: view for view in api.list_integrations_for_member(member, db_session)
    }
    assert listed[detail.id].status.state.value == "not_connected"

    status = api.save_member_connection(
        detail.id,
        ConnectionFieldsRequest(fields={"api_key": "mine"}),
        member,
        db_session,
    )
    assert status.state.value == "connected"

    grants = api.save_action_grants(
        detail.id,
        ActionGrantsUpdate(actions={"set_alert": "allow"}),
        member,
        db_session,
    )
    by_key = {action.key: action for action in grants.actions}
    assert by_key["set_alert"].user_policy == "allow"
    assert by_key["get_forecast"].user_policy is None
    assert api.get_integration_for_member(detail.id, member, db_session).actions[
        0
    ].user_policy in (None, "allow")

    api.save_action_grants(
        detail.id, ActionGrantsUpdate(actions={"set_alert": None}), member, db_session
    )
    assert all(
        action.user_policy is None
        for action in api.get_action_grants(detail.id, member, db_session).actions
    )

    status = api.delete_member_connection(detail.id, member, db_session)
    assert status.state.value == "not_connected"

    admin_api.update_integration(
        detail.id,
        IntegrationUpdate(users_can_save_always_allow=False),
        admin,
        db_session,
    )
    with pytest.raises(OnyxError) as error:
        api.save_action_grants(
            detail.id,
            ActionGrantsUpdate(actions={"set_alert": "allow"}),
            member,
            db_session,
        )
    assert error.value.status_code == 403


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


def test_member_plugin_refs_carry_the_user_choice(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    plugin_id = detail.plugins[0].plugin_id

    for enabled in (False, True):
        set_plugin_preferences__no_commit(member.id, [plugin_id], enabled, db_session)
        db_session.commit()
        listed = {
            view.id: view
            for view in api.list_integrations_for_member(member, db_session)
        }
        assert [(ref.plugin_id, ref.enabled) for ref in listed[detail.id].plugins] == [
            (plugin_id, enabled)
        ]
        member_view = api.get_integration_for_member(detail.id, member, db_session)
        assert [ref.enabled for ref in member_view.plugins] == [enabled]


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


def test_agent_catalog_lists_visible_plugins(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    detail = admin_api.create_integration(_openapi_create(), admin, db_session)
    created.add(detail.id)
    options = {
        option.plugin_id: option for option in api.get_agent_catalog(member, db_session)
    }
    plugin_id = detail.plugins[0].plugin_id
    assert [i.id for i in options[plugin_id].integrations] == [detail.id]
    assert len(options[plugin_id].integrations[0].actions) == 2
    assert options[plugin_id].integrations[0].users_can_save_always_allow


# Agents


def _persona(
    db_session: Session,
    user: User,
    *,
    tool_ids: list[int],
    plugin_links: list[PersonaPluginLink] | None,
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
        plugin_links=plugin_links,
        persona_id=persona_id,
    )
    return persona.id


def test_persona_plugins_and_legacy_tool_ids(
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
    mcp_plugin = hold_in_plugin(db_session, [mcp])
    old_mcp_tool = Tool(
        name="hello",
        description="",
        mcp_server_id=server.id,
        enabled=True,
        passthrough_auth=False,
    )
    db_session.add(old_mcp_tool)
    db_session.commit()

    persona_id = _persona(
        db_session,
        admin,
        tool_ids=[openapi_tool.id, old_mcp_tool.id],
        plugin_links=None,
    )
    links = {
        link.plugin_id: link.action_settings
        for link in list_persona_plugin_links(db_session, persona_id)
    }
    assert links[openapi.plugins[0].plugin_id] == {}
    assert links[mcp_plugin.id] == {
        "default": "blocked",
        "actions": {"hello": "inherit"},
    }

    _persona(
        db_session,
        admin,
        tool_ids=[],
        plugin_links=[
            PersonaPluginLink(
                plugin_id=mcp_plugin.id,
                action_settings=ActionSettings(actions={"bye": LinkValue.BLOCKED}),
            )
        ],
        persona_id=persona_id,
    )
    links = {
        link.plugin_id: link.action_settings
        for link in list_persona_plugin_links(db_session, persona_id)
    }
    assert links == {mcp_plugin.id: {"actions": {"bye": "blocked"}}}

    snapshot = persona_api.get_persona(persona_id, admin, db_session)
    assert [
        (plugin.plugin_id, plugin.plugin_name, plugin.action_settings)
        for plugin in snapshot.plugins
    ] == [
        (
            mcp_plugin.id,
            mcp_plugin.name,
            ActionSettings(actions={"bye": LinkValue.BLOCKED}),
        )
    ]

    # None keeps the links.
    _persona(db_session, admin, tool_ids=[], plugin_links=None, persona_id=persona_id)
    assert len(list_persona_plugin_links(db_session, persona_id)) == 1


def test_persona_create_and_update_responses_carry_plugins() -> None:
    """FastAPI drops each field that the response model does not have."""
    from fastapi.routing import APIRoute

    endpoints = {persona_api.create_persona, persona_api.update_persona}
    models = [
        route.response_model
        for route in persona_api.basic_router.routes
        if isinstance(route, APIRoute) and route.endpoint in endpoints
    ]
    assert models == [FullPersonaSnapshot, FullPersonaSnapshot]
    assert "plugins" in FullPersonaSnapshot.model_fields


# Public aliases


def test_custom_tool_aliases_keep_their_shapes(
    db_session: Session, admin: User, member: User, created: Created
) -> None:
    snapshot = tool_api.create_custom_tool(
        CustomToolCreate(
            name=f"alias-{uuid4().hex[:8]}",
            description="Alias",
            definition=OPENAPI_SPEC,
            custom_headers=[Header(key="X-Api-Key", value="secret-value")],
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
    assert set(ToolSnapshot.model_fields) == set(snapshot.model_dump())
    assert snapshot.definition == OPENAPI_SPEC
    assert snapshot.custom_headers is not None
    assert snapshot.custom_headers[0]["key"] == "X-Api-Key"
    assert snapshot.custom_headers[0]["value"] != "secret-value"
    assert integration.kind is IntegrationKind.API
    assert integration.auth_mode is IntegrationAuthMode.SHARED

    fetched = tool_api.get_custom_tool(snapshot.id, db_session, member)
    assert fetched.id == snapshot.id
    assert snapshot.id in {t.id for t in tool_api.list_tools(db_session, member)}
    assert snapshot.id in {t.id for t in tool_api.list_openapi_tools(db_session, admin)}

    updated = tool_api.update_custom_tool(
        snapshot.id,
        CustomToolUpdate(
            name="Renamed alias",
            custom_headers=[
                Header(key="X-Api-Key", value=snapshot.custom_headers[0]["value"])
            ],
        ),
        db_session,
        admin,
    )
    assert updated.name == "Renamed alias"
    connection = get_connection(db_session, integration.id, None)
    assert connection is not None

    methods = tool_api.validate_tool(
        tool_api.ValidateToolRequest(definition=OPENAPI_SPEC), admin
    )
    assert {method.raw_name for method in methods.methods} == {
        "get_forecast",
        "set_alert",
    }

    tool_api.delete_custom_tool(snapshot.id, db_session, admin)
    assert db_session.get(Integration, integration.id) is None
    assert db_session.get(Tool, snapshot.id) is None
