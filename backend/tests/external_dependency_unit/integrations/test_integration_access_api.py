"""The access settings of an integration, called through the route functions
against the database: the integrations an agent runs, the user's on/off
switch, the install setting, the shares, publishing and the member states."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    PluginInstallationPolicy,
)
from onyx.db.models import Integration, Persona, User, User__UserGroup, UserGroup
from onyx.error_handling.exceptions import OnyxError
from onyx.integrations.models import ActionSettings, LinkValue
from onyx.integrations.policy import agent_link_settings_by_integration
from onyx.server.features.integrations import admin_api, api
from onyx.server.features.integrations.models import (
    IntegrationAccess,
    IntegrationCreate,
    IntegrationEnableRequest,
    IntegrationGroupSettingChange,
    IntegrationGroupSettingsUpdate,
    IntegrationInstallationPolicy,
    IntegrationSharesUpdate,
    IntegrationUpdate,
    MemberIntegrationState,
    OpenApiConfigInput,
)
from tests.external_dependency_unit.conftest import MakeTestUser
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
)
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
    return make_test_user("u15-admin", is_admin=True)


@pytest.fixture
def scoped(make_test_user: MakeTestUser, db_session: Session) -> User:
    user = make_test_user("u15-scoped")
    user.is_group_manager = True
    db_session.commit()
    return user


@pytest.fixture
def member(make_test_user: MakeTestUser) -> User:
    return make_test_user("u15-member")


@pytest.fixture
def other(make_test_user: MakeTestUser) -> User:
    return make_test_user("u15-other")


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
    with (
        patch("onyx.server.features.integrations.api.reload_craft_sessions"),
        patch("onyx.server.features.integrations.admin_api.reload_craft_sessions"),
    ):
        yield


def _create(
    user: User,
    db_session: Session,
    created: list[int],
    *,
    for_organization: bool,
    sign_in: bool = False,
) -> int:
    """An OpenAPI integration. ``sign_in``: it needs an organization key,
    which no one saved."""
    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=for_organization,
            name=f"weather-{uuid4().hex[:8]}",
            auth_mode=(
                IntegrationAuthMode.SHARED if sign_in else IntegrationAuthMode.NONE
            ),
            auth_method=IntegrationAuthMethod.API_KEY if sign_in else None,
            header_template={"X-Api-Key": "{api_key}"} if sign_in else None,
            config=OpenApiConfigInput(openapi_spec=OPENAPI_SPEC),
        ),
        user,
        db_session,
    )
    created.append(detail.id)
    return detail.id


def _member_access(
    user: User, integration_id: int, db_session: Session
) -> IntegrationAccess | None:
    """The access facts in the member list. None: the list leaves the
    integration out."""
    for integration in api.list_integrations_for_member(user, db_session):
        if integration.id == integration_id:
            return integration.access
    return None


def _enabled_in_member_list(
    user: User, integration_id: int, db_session: Session
) -> bool | None:
    access = _member_access(user, integration_id, db_session)
    return access.user_enabled if access is not None else None


def _status(call: Any) -> int:
    with pytest.raises(OnyxError) as error:
        call()
    return error.value.status_code


def _set_enabled(
    user: User, integration_id: int, enabled: bool, db_session: Session
) -> IntegrationAccess:
    return api.set_integration_enabled(
        integration_id, IntegrationEnableRequest(enabled=enabled), user, db_session
    ).access


def _set_policy(
    admin: User,
    integration_id: int,
    policy: PluginInstallationPolicy,
    db_session: Session,
) -> None:
    admin_api.set_integration_installation_policy(
        integration_id,
        IntegrationInstallationPolicy(installation_policy=policy),
        admin,
        db_session,
    )


def _installation_policy(
    db_session: Session, integration_id: int
) -> PluginInstallationPolicy:
    db_session.expire_all()
    return db_session.get_one(Integration, integration_id).installation_policy


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
        name=f"Integration agent {uuid4().hex[:8]}",
        description="Agent with integrations",
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


# Integrations an agent runs


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
    links = {available_id: blocked, private_id: ActionSettings(), -1: blocked}

    def settings(persona_id: int) -> dict[int, ActionSettings]:
        held = agent_link_settings_by_integration(
            db_session,
            scoped.id,
            persona_id,
            links,
            for_everyone_only=for_everyone_only,
        )
        return {
            integration_id: agent_integration.settings
            for integration_id, agent_integration in held.items()
            if integration_id in created
        }

    private = {} if for_everyone_only else {private_id: ActionSettings()}
    # The owner has the private integration on. No user turned on the
    # available ones.
    assert settings(DEFAULT_PERSONA_ID) == private
    assert settings(7) == {available_id: blocked, **private}


def test_default_agent_runs_the_integrations_the_user_turned_on(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    integration_id = _create(admin, db_session, created, for_organization=True)
    assert integration_id not in api.get_agent_integration_ids(
        DEFAULT_PERSONA_ID, member, db_session
    )

    _set_enabled(member, integration_id, True, db_session)
    assert integration_id in api.get_agent_integration_ids(
        DEFAULT_PERSONA_ID, member, db_session
    )
    # The released mobile app reads the same ids as text.
    assert str(integration_id) in api.get_agent_integration_ids_for_mobile(
        DEFAULT_PERSONA_ID, member, db_session
    )

    _set_enabled(member, integration_id, False, db_session)
    assert integration_id not in api.get_agent_integration_ids(
        DEFAULT_PERSONA_ID, member, db_session
    )


def test_agent_runs_the_linked_integrations_the_user_has_access_to(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
    personas: list[Persona],
) -> None:
    """An agent gives no access. A user who turned an integration off still
    gets it on a custom agent."""
    visible_id = _create(admin, db_session, created, for_organization=True)
    private_id = _create(scoped, db_session, created, for_organization=False)
    _create(admin, db_session, created, for_organization=True)
    agent = _persona(admin, db_session, personas, is_public=True)
    link_persona(db_session, agent.id, visible_id)
    link_persona(db_session, agent.id, private_id)

    assert _enabled_in_member_list(member, visible_id, db_session) is False
    assert api.get_agent_integration_ids(agent.id, member, db_session) == [visible_id]
    assert api.get_agent_integration_ids(agent.id, scoped, db_session) == sorted(
        [visible_id, private_id]
    )


def test_agent_integrations_of_a_hidden_agent_are_not_found(
    db_session: Session,
    admin: User,
    member: User,
    created: list[int],  # noqa: ARG001
    personas: list[Persona],
) -> None:
    agent = _persona(admin, db_session, personas, is_public=False)
    assert (
        _status(lambda: api.get_agent_integration_ids(agent.id, member, db_session))
        == 404
    )


# On/off switch


def test_member_turns_an_organization_integration_on_and_off(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    integration_id = _create(admin, db_session, created, for_organization=True)
    assert _enabled_in_member_list(member, integration_id, db_session) is False

    access = _set_enabled(member, integration_id, True, db_session)
    assert (access.user_enabled, access.user_choice, access.installation_policy) == (
        True,
        True,
        PluginInstallationPolicy.AVAILABLE,
    )
    assert _enabled_in_member_list(member, integration_id, db_session) is True

    _set_enabled(member, integration_id, False, db_session)
    assert _enabled_in_member_list(member, integration_id, db_session) is False


def test_a_required_integration_cannot_be_turned_off(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    integration_id = _create(admin, db_session, created, for_organization=True)
    _set_policy(admin, integration_id, PluginInstallationPolicy.REQUIRED, db_session)

    assert (
        _status(lambda: _set_enabled(member, integration_id, False, db_session)) == 400
    )
    db_session.rollback()
    assert _enabled_in_member_list(member, integration_id, db_session) is True


def test_member_cannot_switch_an_integration_with_no_access(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
) -> None:
    private_id = _create(scoped, db_session, created, for_organization=False)
    hidden_id = _create(admin, db_session, created, for_organization=True)
    _set_policy(admin, hidden_id, PluginInstallationPolicy.NOT_AVAILABLE, db_session)

    for integration_id in (private_id, hidden_id, -1):
        with pytest.raises(OnyxError) as error:
            _set_enabled(member, integration_id, True, db_session)
        assert error.value.status_code == 404
        db_session.rollback()


# Member states


def test_a_row_gives_each_of_the_five_states(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
) -> None:
    def state(integration_id: int) -> MemberIntegrationState | None:
        access = _member_access(member, integration_id, db_session)
        return access.state if access is not None else None

    no_sign_in = _create(admin, db_session, created, for_organization=True)
    needs_key = _create(admin, db_session, created, for_organization=True, sign_in=True)
    private_id = _create(scoped, db_session, created, for_organization=False)

    assert state(no_sign_in) is MemberIntegrationState.TURN_ON
    assert _set_enabled(member, no_sign_in, True, db_session).state is (
        MemberIntegrationState.ON
    )
    # On for the user, with no working connection.
    assert _set_enabled(member, needs_key, True, db_session).state is (
        MemberIntegrationState.SIGN_IN
    )

    admin_api.update_integration(
        no_sign_in, IntegrationUpdate(enabled=False), admin, db_session
    )
    assert state(no_sign_in) is MemberIntegrationState.TURNED_OFF

    # A member with no access gets no row. An organization-wide manager sees
    # the integration and has no access to it.
    assert state(private_id) is None
    admin_rows = {
        row.id: row for row in admin_api.list_integrations_admin(admin, db_session)
    }
    private = admin_rows[private_id]
    assert private.access.state is MemberIntegrationState.NO_ACCESS
    assert private.access.can_manage is True
    assert private.access.is_owner is False
    assert private.access.shared_with_everyone is False
    assert private.access.owner_email == scoped.email
    assert private.installation_policy is PluginInstallationPolicy.NOT_AVAILABLE
    assert admin_rows[needs_key].access.shared_with_everyone is True
    assert admin_rows[needs_key].access.is_owner is True
    # The owner of a private integration has it on.
    owner_rows = {
        row.id: row for row in api.list_integrations_for_member(scoped, db_session)
    }
    assert owner_rows[private_id].access.state is MemberIntegrationState.ON
    assert owner_rows[private_id].access.is_owner is True


# Install setting


def test_admin_sets_each_install_setting(
    db_session: Session, admin: User, member: User, created: list[int]
) -> None:
    integration_id = _create(admin, db_session, created, for_organization=True)

    _set_policy(admin, integration_id, PluginInstallationPolicy.DEFAULT, db_session)
    assert _enabled_in_member_list(member, integration_id, db_session) is True
    _set_policy(
        admin, integration_id, PluginInstallationPolicy.NOT_AVAILABLE, db_session
    )
    assert _enabled_in_member_list(member, integration_id, db_session) is None
    for policy in PluginInstallationPolicy:
        _set_policy(admin, integration_id, policy, db_session)
        assert _installation_policy(db_session, integration_id) is policy


def test_install_setting_opens_a_private_integration(
    db_session: Session, admin: User, scoped: User, member: User, created: list[int]
) -> None:
    integration_id = _create(scoped, db_session, created, for_organization=False)
    assert _enabled_in_member_list(member, integration_id, db_session) is None

    _set_policy(admin, integration_id, PluginInstallationPolicy.DEFAULT, db_session)
    assert _enabled_in_member_list(member, integration_id, db_session) is True


# Shares and publishing


def _share(
    user: User, integration_id: int, user_ids: list[UUID], db_session: Session
) -> None:
    api.set_integration_shares(
        integration_id,
        IntegrationSharesUpdate(user_ids=user_ids, group_ids=[]),
        user,
        db_session,
    )


def test_owner_shares_a_private_integration(
    db_session: Session,
    scoped: User,
    member: User,
    other: User,
    created: list[int],
) -> None:
    integration_id = _create(scoped, db_session, created, for_organization=False)
    assert _enabled_in_member_list(member, integration_id, db_session) is None

    _share(scoped, integration_id, [member.id], db_session)
    shares = api.get_integration_shares(integration_id, scoped, db_session)
    assert [(share.user_id, share.email) for share in shares.user_shares] == [
        (member.id, member.email)
    ]
    assert _enabled_in_member_list(member, integration_id, db_session) is False

    # A person with a share uses the integration but does not read or change
    # its shares.
    assert _status(lambda: _share(member, integration_id, [], db_session)) == 403
    db_session.rollback()
    assert (
        _status(lambda: api.get_integration_shares(integration_id, member, db_session))
        == 403
    )
    db_session.rollback()
    assert _status(lambda: _share(other, integration_id, [], db_session)) == 404
    db_session.rollback()

    _share(scoped, integration_id, [], db_session)
    assert _enabled_in_member_list(member, integration_id, db_session) is None


def test_a_scoped_manager_shares_only_its_own_integration(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
) -> None:
    of_admin = _create(admin, db_session, created, for_organization=False)
    _share(admin, of_admin, [scoped.id], db_session)

    assert _status(lambda: _share(scoped, of_admin, [member.id], db_session)) == 403
    db_session.rollback()

    # An organization-wide manager shares the integration of another owner.
    of_scoped = _create(scoped, db_session, created, for_organization=False)
    _share(admin, of_scoped, [member.id], db_session)
    assert _enabled_in_member_list(member, of_scoped, db_session) is False


def test_sharing_setting_off_stops_a_new_share(
    db_session: Session, scoped: User, member: User, created: list[int]
) -> None:
    integration_id = _create(scoped, db_session, created, for_organization=False)
    with patch(
        "onyx.db.plugin.load_settings",
        return_value=type("S", (), {"plugin_sharing": False})(),
    ):
        assert (
            _status(lambda: _share(scoped, integration_id, [member.id], db_session))
            == 403
        )


def test_publish_needs_an_organization_wide_action_manager(
    db_session: Session,
    admin: User,
    scoped: User,
    member: User,
    created: list[int],
) -> None:
    integration_id = _create(scoped, db_session, created, for_organization=False)
    _share(scoped, integration_id, [member.id], db_session)
    publish = lambda user: api.publish_integration(  # noqa: E731
        integration_id, user, db_session
    )
    assert _status(lambda: publish(scoped)) == 403
    db_session.rollback()
    assert _status(lambda: publish(member)) == 403
    db_session.rollback()

    published = publish(admin)
    assert published.installation_policy is PluginInstallationPolicy.AVAILABLE
    assert (
        _installation_policy(db_session, integration_id)
        is PluginInstallationPolicy.AVAILABLE
    )
    assert _enabled_in_member_list(member, integration_id, db_session) is False

    # An integration of the organization has an install setting, not shares.
    assert (
        _status(lambda: _share(admin, integration_id, [member.id], db_session)) == 400
    )
    db_session.rollback()
    assert _status(lambda: publish(admin)) == 400


@pytest.fixture
def group(db_session: Session, member: User) -> Generator[UserGroup, None, None]:
    """A group with ``member`` in it, deleted after the test."""
    made = make_group(db_session)
    add_user_to_group(db_session, member, made)
    db_session.commit()
    try:
        yield made
    finally:
        db_session.rollback()
        db_session.execute(
            delete(User__UserGroup).where(User__UserGroup.user_group_id == made.id)
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id == made.id))
        db_session.commit()


def _set_group_setting(
    user: User,
    integration_id: int,
    group_id: int,
    policy: PluginInstallationPolicy | None,
    db_session: Session,
) -> None:
    admin_api.set_integration_group_settings(
        integration_id,
        IntegrationGroupSettingsUpdate(
            group_settings=[
                IntegrationGroupSettingChange(
                    group_id=group_id, installation_policy=policy
                )
            ]
        ),
        user,
        db_session,
    )


def _member_state(
    user: User, integration_id: int, db_session: Session
) -> MemberIntegrationState | None:
    access = _member_access(user, integration_id, db_session)
    return access.state if access is not None else None


def test_a_group_setting_gives_the_group_access_and_others_see_no_access(
    db_session: Session,
    admin: User,
    member: User,
    other: User,
    group: UserGroup,
    created: list[int],
) -> None:
    integration_id = _create(admin, db_session, created, for_organization=False)
    assert _member_state(member, integration_id, db_session) is None
    assert _member_state(other, integration_id, db_session) is None

    _set_group_setting(
        admin, integration_id, group.id, PluginInstallationPolicy.AVAILABLE, db_session
    )
    detail = admin_api.get_integration_admin(integration_id, admin, db_session)
    assert [
        (setting.group_id, setting.installation_policy)
        for setting in detail.group_settings
    ] == [(group.id, PluginInstallationPolicy.AVAILABLE)]
    assert (
        _member_state(member, integration_id, db_session)
        is MemberIntegrationState.TURN_ON
    )
    [row] = [
        row
        for row in api.list_integrations_for_member(other, db_session)
        if row.id == integration_id
    ]
    assert row.access.state is MemberIntegrationState.NO_ACCESS
    # A No access row shows no configuration and no owner.
    assert (row.access.owner_email, row.credential_fields, row.server_url) == (
        None,
        [],
        None,
    )

    _set_group_setting(admin, integration_id, group.id, None, db_session)
    assert (
        admin_api.get_integration_admin(
            integration_id, admin, db_session
        ).group_settings
        == []
    )
    assert _member_state(member, integration_id, db_session) is None
    assert _member_state(other, integration_id, db_session) is None


def test_a_group_setting_keeps_the_shares(
    db_session: Session,
    admin: User,
    other: User,
    group: UserGroup,
    created: list[int],
) -> None:
    integration_id = _create(admin, db_session, created, for_organization=False)
    _share(admin, integration_id, [other.id], db_session)

    _set_group_setting(
        admin, integration_id, group.id, PluginInstallationPolicy.DEFAULT, db_session
    )

    assert [
        share.user_id
        for share in api.get_integration_shares(
            integration_id, admin, db_session
        ).user_shares
    ] == [other.id]
    assert (
        _member_state(other, integration_id, db_session)
        is MemberIntegrationState.TURN_ON
    )


def test_a_group_share_of_a_private_integration_stays_hidden(
    db_session: Session,
    admin: User,
    other: User,
    group: UserGroup,
    created: list[int],
) -> None:
    integration_id = _create(admin, db_session, created, for_organization=False)
    api.set_integration_shares(
        integration_id,
        IntegrationSharesUpdate(user_ids=[], group_ids=[group.id]),
        admin,
        db_session,
    )
    assert _member_state(other, integration_id, db_session) is None


def test_only_an_organization_wide_manager_sets_a_group_setting(
    db_session: Session,
    scoped: User,
    group: UserGroup,
    created: list[int],
) -> None:
    integration_id = _create(scoped, db_session, created, for_organization=False)
    assert (
        _status(
            lambda: _set_group_setting(
                scoped,
                integration_id,
                group.id,
                PluginInstallationPolicy.AVAILABLE,
                db_session,
            )
        )
        == 403
    )
