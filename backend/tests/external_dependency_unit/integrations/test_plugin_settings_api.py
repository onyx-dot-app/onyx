"""The access settings of an integration, called through the route functions
that name it by its plugin, against the database: the plugins an agent runs,
the user's on/off switch, the install setting, the shares and publishing."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    MarketplaceKind,
    Permission,
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    Integration,
    Marketplace,
    Persona,
    Plugin,
    Plugin__Integration,
    PluginSkill,
    User,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import ActionSettings, LinkValue
from onyx.integrations.policy import agent_link_settings_by_integration
from onyx.server.features.integrations import admin_api, api, plugins_api
from onyx.server.features.integrations.models import (
    IntegrationCreate,
    OpenApiConfigInput,
    PluginAccessUpdate,
    PluginEnableRequest,
    PluginInstallationPolicyUpdate,
    PluginUserShare,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.craft.db_helpers import share_plugin_with_user
from tests.external_dependency_unit.integration_helpers import (
    delete_integrations,
    link_persona,
)

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Weather", "description": "Weather", "version": "1.0"},
    "servers": [{"url": "https://weather.example.com"}],
    "paths": {
        "/forecast": {"get": {"operationId": "get_forecast", "summary": "Forecast"}}
    },
}


@pytest.fixture
def admin(make_test_user: MakeTestUser) -> User:
    return make_test_user("u6p-admin", is_admin=True)


@pytest.fixture
def scoped(make_test_user: MakeTestUser, db_session: Session) -> User:
    user = make_test_user("u6p-scoped")
    user.is_group_manager = True
    db_session.commit()
    return user


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("u6p-member")


@pytest.fixture
def other(make_test_user: MakeTestUser) -> User:
    return make_test_user("u6p-other")


@pytest.fixture
def created(
    db_session: Session,
    admin: User,  # noqa: ARG001
    scoped: User,  # noqa: ARG001
    member: User,  # noqa: ARG001
    other: User,  # noqa: ARG001
) -> Generator[list[int], None, None]:
    ids: list[int] = []
    try:
        yield ids
    finally:
        delete_integrations(db_session, ids)


@pytest.fixture(autouse=True)
def no_craft_reload() -> Generator[None, None, None]:
    with patch("onyx.server.features.integrations.plugins_api.reload_craft_sessions"):
        yield


def _create(
    user: User,
    db_session: Session,
    created: list[int],
    *,
    for_organization: bool,
    name: str | None = None,
) -> UUID:
    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=for_organization,
            name=name or f"weather-{uuid4().hex[:8]}",
            auth_mode=IntegrationAuthMode.SHARED,
            auth_method=IntegrationAuthMethod.API_KEY,
            header_template={"X-Api-Key": "{api_key}"},
            config=OpenApiConfigInput(openapi_spec=OPENAPI_SPEC),
        ),
        user,
        db_session,
    )
    created.append(detail.id)
    return detail.plugins[0].plugin_id


def _integration(db_session: Session, plugin_id: UUID) -> Integration:
    """The integration that the plugin id names, read again from the database."""
    db_session.expire_all()
    return db_session.scalars(
        select(Integration)
        .join(Plugin__Integration, Plugin__Integration.integration_id == Integration.id)
        .where(Plugin__Integration.plugin_id == plugin_id)
    ).one()


def _enabled_in_member_list(
    user: User, plugin_id: UUID, db_session: Session
) -> bool | None:
    for integration in api.list_integrations_for_member(user, db_session):
        for ref in integration.plugins:
            if ref.plugin_id == plugin_id:
                return ref.enabled
    return None


def _status(call: Any) -> int:
    with pytest.raises(OnyxError) as error:
        call()
    return error.value.status_code


def _set_policy(
    admin: User,
    plugin_id: UUID,
    policy: PluginInstallationPolicy,
    db_session: Session,
) -> None:
    plugins_api.set_plugin_installation_policy(
        plugin_id,
        PluginInstallationPolicyUpdate(installation_policy=policy),
        admin,
        db_session,
    )


@pytest.fixture
def personas(db_session: Session) -> Generator[list[Persona], None, None]:
    made: list[Persona] = []
    try:
        yield made
    finally:
        db_session.rollback()
        for persona in made:
            persona.deleted = True
        db_session.commit()


def _persona(
    owner: User, db_session: Session, personas: list[Persona], *, is_public: bool
) -> Persona:
    persona = Persona(
        name=f"Plugin agent {uuid4().hex[:8]}",
        description="Agent with plugins",
        system_prompt="You are a helpful assistant",
        task_prompt="",
        tools=[],
        document_sets=[],
        user_id=owner.id,
        groups=[],
        is_listed=True,
        is_public=is_public,
        display_priority=None,
        starter_messages=None,
        deleted=False,
    )
    db_session.add(persona)
    db_session.commit()
    personas.append(persona)
    return persona


# Plugins an agent runs


@pytest.mark.parametrize("for_everyone_only", [False, True])
def test_agent_integrations_keep_the_settings_of_their_links(
    db_session: Session,
    admin: User,
    scoped: User,
    created: list[int],
    for_everyone_only: bool,
) -> None:
    """The default agent uses the integrations that the user turned on. A
    custom agent uses the linked integrations that the user has access to.
    Each one keeps the settings of its link."""
    available_id = _create(admin, db_session, created, for_organization=True)
    private_id = _create(scoped, db_session, created, for_organization=False)
    _create(admin, db_session, created, for_organization=True)
    blocked = ActionSettings(default=LinkValue.BLOCKED)
    links = {available_id: blocked, private_id: ActionSettings(), uuid4(): blocked}

    def settings(persona_id: int) -> dict[UUID, ActionSettings | None]:
        held = agent_link_settings_by_integration(
            db_session,
            scoped.id,
            persona_id,
            links,
            for_everyone_only=for_everyone_only,
        )
        return {
            plugin_id: setting
            for links_of in held.values()
            for plugin_id, setting in zip(
                links_of.plugin_ids, links_of.settings, strict=True
            )
        }

    private = {} if for_everyone_only else {private_id: ActionSettings()}
    # The owner has the private integration on. No user turned on the
    # available ones.
    assert settings(DEFAULT_PERSONA_ID) == private
    assert settings(7) == {available_id: blocked, **private}


def test_default_agent_runs_the_plugins_the_user_turned_on(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    plugin_id = _create(admin, db_session, created, for_organization=True)
    assert plugin_id not in plugins_api.get_agent_plugin_ids(
        DEFAULT_PERSONA_ID, member, db_session
    )

    plugins_api.set_plugin_enabled(
        plugin_id, PluginEnableRequest(enabled=True), member, db_session
    )
    assert plugin_id in plugins_api.get_agent_plugin_ids(
        DEFAULT_PERSONA_ID, member, db_session
    )


def test_agent_runs_the_linked_plugins_the_user_can_see(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
    personas: list[Persona],
) -> None:
    visible_id = _create(admin, db_session, created, for_organization=True)
    private_id = _create(scoped, db_session, created, for_organization=False)
    _create(admin, db_session, created, for_organization=True)
    agent = _persona(admin, db_session, personas, is_public=True)
    link_persona(db_session, agent.id, visible_id)
    link_persona(db_session, agent.id, private_id)

    assert plugins_api.get_agent_plugin_ids(agent.id, member, db_session) == [
        visible_id
    ]
    assert plugins_api.get_agent_plugin_ids(agent.id, scoped, db_session) == sorted(
        [visible_id, private_id], key=str
    )


def test_agent_plugins_of_a_hidden_agent_are_not_found(
    db_session: Session,
    admin: User,
    member: User,
    created: list[int],  # noqa: ARG001
    personas: list[Persona],
) -> None:
    agent = _persona(admin, db_session, personas, is_public=False)
    assert (
        _status(lambda: plugins_api.get_agent_plugin_ids(agent.id, member, db_session))
        == 404
    )


# On/off switch


def test_member_turns_an_organization_plugin_on_and_off(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    plugin_id = _create(admin, db_session, created, for_organization=True)
    assert _enabled_in_member_list(member, plugin_id, db_session) is False

    state = plugins_api.set_plugin_enabled(
        plugin_id, PluginEnableRequest(enabled=True), member, db_session
    )
    assert (state.enabled, state.installation_policy) == (
        True,
        PluginInstallationPolicy.AVAILABLE,
    )
    assert _enabled_in_member_list(member, plugin_id, db_session) is True

    plugins_api.set_plugin_enabled(
        plugin_id, PluginEnableRequest(enabled=False), member, db_session
    )
    assert _enabled_in_member_list(member, plugin_id, db_session) is False


def test_a_required_plugin_cannot_be_turned_off(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    plugin_id = _create(admin, db_session, created, for_organization=True)
    _set_policy(admin, plugin_id, PluginInstallationPolicy.REQUIRED, db_session)

    assert (
        _status(
            lambda: plugins_api.set_plugin_enabled(
                plugin_id, PluginEnableRequest(enabled=False), member, db_session
            )
        )
        == 400
    )
    db_session.rollback()
    assert _enabled_in_member_list(member, plugin_id, db_session) is True


def test_member_cannot_switch_a_plugin_it_cannot_see(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
) -> None:
    private_id = _create(scoped, db_session, created, for_organization=False)
    hidden_id = _create(admin, db_session, created, for_organization=True)
    _set_policy(admin, hidden_id, PluginInstallationPolicy.NOT_AVAILABLE, db_session)

    for plugin_id in (private_id, hidden_id, uuid4()):
        with pytest.raises(OnyxError) as error:
            plugins_api.set_plugin_enabled(
                plugin_id, PluginEnableRequest(enabled=True), member, db_session
            )
        assert error.value.status_code == 404
        db_session.rollback()


def test_switch_refuses_a_plugin_that_holds_a_skill(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    plugin_id = _create(admin, db_session, created, for_organization=True)
    plugin = db_session.get(Plugin, plugin_id)
    assert plugin is not None
    db_session.add(
        PluginSkill(
            plugin_version_id=plugin.current_version_id,
            path="",
            frontmatter={"name": f"skill-{uuid4().hex[:8]}", "description": "d"},
        )
    )
    db_session.commit()

    assert (
        _status(
            lambda: plugins_api.set_plugin_enabled(
                plugin_id, PluginEnableRequest(enabled=True), member, db_session
            )
        )
        == 400
    )


# Install setting


def test_admin_sets_each_install_setting(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    plugin_id = _create(admin, db_session, created, for_organization=True)

    _set_policy(admin, plugin_id, PluginInstallationPolicy.DEFAULT, db_session)
    assert _enabled_in_member_list(member, plugin_id, db_session) is True
    _set_policy(admin, plugin_id, PluginInstallationPolicy.NOT_AVAILABLE, db_session)
    assert _enabled_in_member_list(member, plugin_id, db_session) is None
    for policy in PluginInstallationPolicy:
        _set_policy(admin, plugin_id, policy, db_session)
        assert _integration(db_session, plugin_id).installation_policy is policy


def test_install_setting_opens_a_private_integration(
    db_session: Session, admin: User, scoped: User, member: User, created: list[int]
) -> None:
    plugin_id = _create(scoped, db_session, created, for_organization=False)
    assert _enabled_in_member_list(member, plugin_id, db_session) is None

    _set_policy(admin, plugin_id, PluginInstallationPolicy.DEFAULT, db_session)
    assert _enabled_in_member_list(member, plugin_id, db_session) is True


def test_a_share_of_the_plugin_gives_no_integration(
    db_session: Session, scoped: User, member: User, created: list[int]
) -> None:
    """The plugin id only names the integration. A person who can see the
    plugin has no access to the integration."""
    plugin_id = _create(scoped, db_session, created, for_organization=False)
    share_plugin_with_user(
        db_session, plugin_id, member.id, SkillSharePermission.VIEWER
    )
    db_session.commit()

    assert _enabled_in_member_list(member, plugin_id, db_session) is None
    assert (
        _status(
            lambda: plugins_api.set_plugin_enabled(
                plugin_id, PluginEnableRequest(enabled=True), member, db_session
            )
        )
        == 404
    )


# Shares and publishing


def _http_request(token_scopes: list[Permission] | None = None) -> Request:
    request = Request({"type": "http"})
    if token_scopes is not None:
        request.state.token_scopes = token_scopes
    return request


def _share(
    user: User,
    plugin_id: UUID,
    user_ids: list[UUID],
    db_session: Session,
    token_scopes: list[Permission] | None = None,
) -> None:
    plugins_api.share_plugin(
        _http_request(token_scopes),
        plugin_id,
        PluginAccessUpdate(
            user_shares=[
                PluginUserShare(user_id=user_id, permission=SkillSharePermission.VIEWER)
                for user_id in user_ids
            ],
            group_shares=[],
        ),
        user,
        db_session,
    )


def test_owner_shares_a_private_plugin(
    db_session: Session,
    scoped: User,
    member: User,
    other: User,
    created: list[int],
) -> None:
    plugin_id = _create(scoped, db_session, created, for_organization=False)
    assert _enabled_in_member_list(member, plugin_id, db_session) is None

    _share(scoped, plugin_id, [member.id], db_session)
    access = plugins_api.get_plugin_access(
        _http_request(), plugin_id, scoped, db_session
    )
    assert [(share.user_id, share.email) for share in access.user_shares] == [
        (member.id, member.email)
    ]
    assert _enabled_in_member_list(member, plugin_id, db_session) is False

    # A person with a share sees the plugin but does not change its shares.
    assert _status(lambda: _share(member, plugin_id, [], db_session)) == 403
    db_session.rollback()
    assert _status(lambda: _share(other, plugin_id, [], db_session)) == 404
    db_session.rollback()

    _share(scoped, plugin_id, [], db_session)
    assert _enabled_in_member_list(member, plugin_id, db_session) is None


def test_a_basic_token_reaches_only_the_plugins_of_its_user(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
) -> None:
    plugin_id = _create(scoped, db_session, created, for_organization=False)
    basic = [Permission.BASIC_ACCESS]

    assert (
        _status(
            lambda: plugins_api.get_plugin_access(
                _http_request(basic), plugin_id, admin, db_session
            )
        )
        == 404
    )
    db_session.rollback()
    assert (
        _status(lambda: _share(admin, plugin_id, [member.id], db_session, basic)) == 404
    )
    db_session.rollback()
    assert (
        _status(
            lambda: plugins_api.publish_plugin(
                _http_request(basic), plugin_id, admin, db_session
            )
        )
        == 404
    )
    db_session.rollback()

    _share(scoped, plugin_id, [member.id], db_session, basic)
    access = plugins_api.get_plugin_access(
        _http_request(basic), plugin_id, scoped, db_session
    )
    assert [share.user_id for share in access.user_shares] == [member.id]

    own_plugin_id = _create(admin, db_session, created, for_organization=False)
    assert (
        _status(
            lambda: plugins_api.publish_plugin(
                _http_request(basic), own_plugin_id, admin, db_session
            )
        )
        == 403
    )


def test_publish_keeps_the_plugin_as_it_is(
    db_session: Session, admin: User, created: list[int]
) -> None:
    """A publish changes the install setting of the integration. The plugin
    keeps its name and its place, also when the organization has the name."""
    name = f"weather-{uuid4().hex[:8]}"
    _create(admin, db_session, created, for_organization=True, name=name)
    plugin_id = _create(admin, db_session, created, for_organization=False, name=name)

    published = plugins_api.publish_plugin(
        _http_request(), plugin_id, admin, db_session
    )

    assert published.name == name
    plugin = db_session.get(Plugin, plugin_id)
    assert plugin is not None
    kind = db_session.scalar(
        select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
    )
    assert kind is MarketplaceKind.USER_UPLOADS


def test_sharing_setting_off_stops_a_new_share(
    db_session: Session, scoped: User, member: User, created: list[int]
) -> None:
    plugin_id = _create(scoped, db_session, created, for_organization=False)
    with patch(
        "onyx.db.plugin.load_settings",
        return_value=type("S", (), {"plugin_sharing": False})(),
    ):
        assert _status(lambda: _share(scoped, plugin_id, [member.id], db_session)) == (
            403
        )


def test_publish_needs_an_organization_wide_action_manager(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
) -> None:
    plugin_id = _create(scoped, db_session, created, for_organization=False)
    publish = lambda user: plugins_api.publish_plugin(  # noqa: E731
        _http_request(), plugin_id, user, db_session
    )
    assert _status(lambda: publish(scoped)) == 403
    db_session.rollback()
    assert _status(lambda: publish(member)) == 404
    db_session.rollback()

    published = publish(admin)
    assert published.plugin_id == plugin_id
    assert (
        _integration(db_session, plugin_id).installation_policy
        is PluginInstallationPolicy.AVAILABLE
    )
    assert _enabled_in_member_list(member, plugin_id, db_session) is False

    # An integration of the organization has an install setting, not shares.
    assert _status(lambda: _share(admin, plugin_id, [member.id], db_session)) == 400
