"""The group plugins API (G4): list the plugins of a group and change a
group's install setting, also on a setting-only row."""

from collections.abc import Generator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ee.onyx.server.user_group.models import UserGroupPlugin
from onyx.db.engine.sql_engine import SqlEngine, get_session_with_current_tenant
from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.models import Plugin, Plugin__UserGroup, User__UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.server.features.skill.models import SkillResponse
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser, DATestUserGroup


@pytest.fixture(autouse=True)
def _db_access() -> Generator[None, None, None]:
    SqlEngine.init_engine(pool_size=10, max_overflow=5)
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def _plugins_url(group_id: int) -> str:
    return f"{API_SERVER_URL}/manage/admin/user-group/{group_id}/plugins"


def _list(user: DATestUser, group_id: int) -> dict[UUID, UserGroupPlugin]:
    response = client.get(_plugins_url(group_id), headers=user.headers)
    response.raise_for_status()
    rows = [UserGroupPlugin.model_validate(row) for row in response.json()]
    return {row.plugin_id: row for row in rows}


def _set(
    user: DATestUser, group_id: int, plugin_id: UUID, policy: str | None
) -> httpx.Response:
    return client.put(
        f"{_plugins_url(group_id)}/{plugin_id}",
        json={"installation_policy": policy},
        headers=user.headers,
    )


def _share(user: DATestUser, skill_id: UUID, body: dict[str, Any]) -> httpx.Response:
    return client.patch(
        f"{API_SERVER_URL}/skills/custom/{skill_id}/share",
        json=body,
        headers=user.headers,
    )


def _group_row(
    plugin_id: UUID, group_id: int
) -> tuple[SkillSharePermission | None, PluginInstallationPolicy | None] | None:
    with get_session_with_current_tenant() as db_session:
        row = db_session.execute(
            select(
                Plugin__UserGroup.permission, Plugin__UserGroup.installation_policy
            ).where(
                Plugin__UserGroup.plugin_id == plugin_id,
                Plugin__UserGroup.user_group_id == group_id,
            )
        ).one_or_none()
        return None if row is None else (row[0], row[1])


def _create_in_groups(
    author: DATestUser, admin: DATestUser, name: str, group_ids: list[int]
) -> SkillResponse:
    """A private skill of ``author`` that an admin shares with the groups."""
    skill = SkillManager.create_custom(author, name=name)
    return SkillManager.replace_group_shares(skill, group_ids, admin)


def _visible_ids(user: DATestUser) -> set[UUID]:
    return {skill.id for skill in SkillManager.list_for_user(user).customs}


def _promote_to_manager(user_id: str, group_id: int) -> None:
    with get_session_with_current_tenant() as db_session:
        promoted = db_session.scalars(
            update(User__UserGroup)
            .where(
                User__UserGroup.user_id == UUID(user_id),
                User__UserGroup.user_group_id == group_id,
            )
            .values(is_manager=True)
            .returning(User__UserGroup.user_id)
        ).all()
        assert len(promoted) == 1
        recompute_user_permissions__no_commit(UUID(user_id), db_session)
        db_session.commit()


def test_list_shows_share_rows_setting_rows_and_skill_names(
    admin_user: DATestUser,
) -> None:
    author = UserManager.create(name=_name("gp_author"))
    group = UserGroupManager.create(admin_user, name=_name("gp-list"))

    shared = _create_in_groups(author, admin_user, _name("gp-shared"), [group.id])
    published = SkillManager.create_custom(
        author, name=_name("gp-published"), is_public=True
    )
    # A second upload with the same name gets the next free plugin name; the
    # group page still shows the skill name.
    skill_name = _name("gp-same")
    SkillManager.create_custom(author, name=skill_name)
    renamed = SkillManager.replace_group_shares(
        SkillManager.create_custom(author, name=skill_name, auto_enable=False),
        [group.id],
        admin_user,
    )
    with get_session_with_current_tenant() as db_session:
        plugin_name = db_session.scalar(
            select(Plugin.name).where(Plugin.id == renamed.id)
        )
    assert plugin_name != skill_name

    _set(admin_user, group.id, published.id, "REQUIRED").raise_for_status()

    rows = _list(admin_user, group.id)
    assert set(rows) == {shared.id, published.id, renamed.id}

    share_row = rows[shared.id]
    assert share_row.permission == SkillSharePermission.VIEWER
    assert share_row.installation_policy is None
    assert not share_row.published
    assert share_row.kind == "skill"
    assert share_row.can_edit

    setting_row = rows[published.id]
    assert setting_row.permission is None
    assert setting_row.installation_policy == PluginInstallationPolicy.REQUIRED
    assert setting_row.company_installation_policy == PluginInstallationPolicy.AVAILABLE
    assert setting_row.published

    assert rows[renamed.id].kind == "skill"
    assert rows[renamed.id].name == skill_name


def test_setting_only_row_changes_what_a_member_gets(admin_user: DATestUser) -> None:
    author = UserManager.create(name=_name("gp_so_author"))
    member = UserManager.create(name=_name("gp_so_member"))
    group = UserGroupManager.create(
        admin_user, name=_name("gp-so"), user_ids=[member.id]
    )
    skill = SkillManager.create_custom(author, name=_name("gp-so"), is_public=True)
    before = SkillManager.get_for_user(skill.id, member)
    assert not before.enabled and before.can_toggle

    _set(admin_user, group.id, skill.id, "REQUIRED").raise_for_status()
    assert _group_row(skill.id, group.id) == (None, PluginInstallationPolicy.REQUIRED)
    required = SkillManager.get_for_user(skill.id, member)
    assert required.enabled and not required.can_toggle

    # A group setting replaces the company setting, also when it is stricter.
    _set(admin_user, group.id, skill.id, "NOT_AVAILABLE").raise_for_status()
    assert skill.id not in _visible_ids(member)

    # Removing the setting deletes a row with no permission.
    _set(admin_user, group.id, skill.id, None).raise_for_status()
    assert _group_row(skill.id, group.id) is None
    assert skill.id not in _list(admin_user, group.id)
    assert skill.id in _visible_ids(member)


def test_change_and_remove_a_setting_on_a_share(admin_user: DATestUser) -> None:
    author = UserManager.create(name=_name("gp_share_author"))
    member = UserManager.create(name=_name("gp_share_member"))
    group = UserGroupManager.create(
        admin_user, name=_name("gp-share"), user_ids=[member.id]
    )
    skill = _create_in_groups(author, admin_user, _name("gp-share"), [group.id])

    rows = _set(admin_user, group.id, skill.id, "DEFAULT")
    rows.raise_for_status()
    assert UserGroupPlugin.model_validate(rows.json()[0]).installation_policy == (
        PluginInstallationPolicy.DEFAULT
    )
    assert SkillManager.get_for_user(skill.id, member).enabled

    _set(admin_user, group.id, skill.id, None).raise_for_status()
    assert _group_row(skill.id, group.id) == (SkillSharePermission.VIEWER, None)


def test_add_a_private_plugin_to_a_group(admin_user: DATestUser) -> None:
    author = UserManager.create(name=_name("gp_add_author"))
    member = UserManager.create(name=_name("gp_add_member"))
    group = UserGroupManager.create(
        admin_user, name=_name("gp-add"), user_ids=[member.id]
    )
    skill = SkillManager.create_custom(author, name=_name("gp-add"))
    assert skill.id not in _visible_ids(member)

    _set(admin_user, group.id, skill.id, "DEFAULT").raise_for_status()
    assert _group_row(skill.id, group.id) == (
        SkillSharePermission.VIEWER,
        PluginInstallationPolicy.DEFAULT,
    )
    assert SkillManager.get_for_user(skill.id, member).enabled


def test_shared_group_with_not_available_is_refused(admin_user: DATestUser) -> None:
    """A group with a share cannot be Not available, with the setting set
    before or after the share."""
    author = UserManager.create(name=_name("gp_na_author"))
    group = UserGroupManager.create(admin_user, name=_name("gp-na"))
    skill = SkillManager.create_custom(author, name=_name("gp-na"))
    share = {"group_shares": [{"group_id": group.id, "permission": "VIEWER"}]}
    _share(admin_user, skill.id, share).raise_for_status()

    response = _set(admin_user, group.id, skill.id, "NOT_AVAILABLE")
    assert response.status_code == 400
    assert "Remove the group's share first" in response.json()["detail"]
    assert _group_row(skill.id, group.id) == (SkillSharePermission.VIEWER, None)

    setting_first = SkillManager.create_custom(
        author, name=_name("gp-na-first"), is_public=True
    )
    _set(admin_user, group.id, setting_first.id, "NOT_AVAILABLE").raise_for_status()
    assert _share(admin_user, setting_first.id, share).status_code == 400
    assert _group_row(setting_first.id, group.id) == (
        None,
        PluginInstallationPolicy.NOT_AVAILABLE,
    )


def test_member_cannot_read_or_change_group_plugins(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    group = UserGroupManager.create(admin_user, name=_name("gp-member"))
    skill = SkillManager.create_custom(admin_user, name=_name("gp-member"))
    assert (
        client.get(_plugins_url(group.id), headers=basic_user.headers).status_code
        == 403
    )
    assert _set(basic_user, group.id, skill.id, "DEFAULT").status_code == 403


# --- Group managers ----------------------------------------------------------


@pytest.fixture
def manager_env(
    admin_user: DATestUser,
) -> tuple[DATestUser, DATestUserGroup, DATestUserGroup]:
    manager = UserManager.create(name=_name("gp_manager"))
    managed = UserGroupManager.create(
        admin_user, name=_name("gp-managed"), user_ids=[manager.id]
    )
    other = UserGroupManager.create(admin_user, name=_name("gp-other"))
    _promote_to_manager(manager.id, managed.id)
    return manager, managed, other


def test_group_manager_sets_a_private_plugin_in_their_group(
    manager_env: tuple[DATestUser, DATestUserGroup, DATestUserGroup],
) -> None:
    manager, managed, _other = manager_env
    skill = SkillManager.create_custom(
        manager, name=_name("gp-scoped"), group_ids=[managed.id]
    )
    _set(manager, managed.id, skill.id, "REQUIRED").raise_for_status()
    rows = _list(manager, managed.id)
    assert rows[skill.id].installation_policy == PluginInstallationPolicy.REQUIRED
    assert rows[skill.id].can_edit


def test_group_manager_refusals(
    admin_user: DATestUser,
    manager_env: tuple[DATestUser, DATestUserGroup, DATestUserGroup],
) -> None:
    manager, managed, other = manager_env
    author = UserManager.create(name=_name("gp_scoped_author"))

    # Another group: the manager cannot read or change it.
    in_other = _create_in_groups(author, admin_user, _name("gp-in-other"), [other.id])
    assert (
        client.get(_plugins_url(other.id), headers=manager.headers).status_code == 404
    )
    assert _set(manager, other.id, in_other.id, "DEFAULT").status_code == 404

    # A published plugin: only an organization-wide manager sets it.
    published = SkillManager.create_custom(
        author, name=_name("gp-scoped-pub"), is_public=True
    )
    response = _set(manager, managed.id, published.id, "REQUIRED")
    assert response.status_code == 403
    assert _group_row(published.id, managed.id) is None
    _set(admin_user, managed.id, published.id, "DEFAULT").raise_for_status()
    assert not _list(manager, managed.id)[published.id].can_edit
    assert _set(manager, managed.id, published.id, None).status_code == 403

    # A private plugin shared outside the manager's groups.
    outside = _create_in_groups(
        author, admin_user, _name("gp-outside"), [managed.id, other.id]
    )
    assert not _list(manager, managed.id)[outside.id].can_edit
    assert _set(manager, managed.id, outside.id, "REQUIRED").status_code == 403
    assert _group_row(outside.id, managed.id) == (SkillSharePermission.VIEWER, None)

    # A private plugin the manager cannot edit is not added to their group.
    unshared = SkillManager.create_custom(author, name=_name("gp-unshared"))
    assert _set(manager, managed.id, unshared.id, "DEFAULT").status_code == 403
    assert _group_row(unshared.id, managed.id) is None
