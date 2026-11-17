"""The settings of a plugin that holds only integrations, called through its
route functions against the database: the user's on/off switch, the install
setting, the shares and publishing."""

from collections.abc import Generator
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    MarketplaceKind,
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import Marketplace, Plugin, PluginSkill, User
from onyx.error_handling.exceptions import OnyxError
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
from tests.external_dependency_unit.integration_helpers import delete_integrations

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
    user: User, db_session: Session, created: list[int], *, for_organization: bool
) -> UUID:
    detail = admin_api.create_integration(
        IntegrationCreate(
            for_organization=for_organization,
            name=f"weather-{uuid4().hex[:8]}",
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
        db_session.expire_all()
        stored = db_session.get(Plugin, plugin_id)
        assert stored is not None and stored.installation_policy is policy


def test_install_setting_needs_an_organization_library_plugin(
    db_session: Session, admin: User, scoped: User, created: list[int]
) -> None:
    plugin_id = _create(scoped, db_session, created, for_organization=False)
    assert (
        _status(
            lambda: _set_policy(
                admin, plugin_id, PluginInstallationPolicy.DEFAULT, db_session
            )
        )
        == 400
    )


# Shares and publishing


def _share(
    user: User, plugin_id: UUID, user_ids: list[UUID], db_session: Session
) -> None:
    plugins_api.share_plugin(
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
    access = plugins_api.get_plugin_access(plugin_id, scoped, db_session)
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
        plugin_id, user, db_session
    )
    assert _status(lambda: publish(scoped)) == 403
    db_session.rollback()
    assert _status(lambda: publish(member)) == 404
    db_session.rollback()

    assert publish(admin).status_code == 204
    db_session.expire_all()
    plugin = db_session.get(Plugin, plugin_id)
    assert plugin is not None
    assert plugin.published_version_id == plugin.current_version_id
    kind = db_session.scalar(
        select(Marketplace.kind).where(Marketplace.id == plugin.marketplace_id)
    )
    assert kind is MarketplaceKind.ORGANIZATION_LIBRARY
    assert _enabled_in_member_list(member, plugin_id, db_session) is False

    # A published plugin has an install setting, not shares.
    assert _status(lambda: _share(admin, plugin_id, [member.id], db_session)) == 400
