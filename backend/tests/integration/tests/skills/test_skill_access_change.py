"""Single share and bulk share apply one access change to the plugin of each
skill, with one set of rules.

Some tests write group install settings directly and read the plugin rows
from the database."""

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.models import (
    Plugin,
    Plugin__User,
    Plugin__UserGroup,
    Skill,
)
from onyx.server.features.skill.models import SkillBulkResponse
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.skill import SkillManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.managers.user_group import UserGroupManager
from tests.integration.common_utils.test_models import DATestUser, DATestUserGroup
from tests.integration.tests.skills.conftest import (
    promote_to_manager,
    share_skill,
    unique_name,
)
from tests.utils.plugin_access import plugin_access_mismatches


def _group(admin: DATestUser, user_ids: list[str] | None = None) -> DATestUserGroup:
    return UserGroupManager.create(
        admin, name=unique_name("access-group"), user_ids=user_ids or []
    )


def _bulk_share(
    user: DATestUser, skill_ids: list[UUID], sharing: dict[str, Any]
) -> SkillBulkResponse:
    response = client.post(
        f"{API_SERVER_URL}/skills/bulk",
        json={
            "action": "share",
            "skill_ids": [str(skill_id) for skill_id in skill_ids],
            "sharing": sharing,
        },
        headers=user.headers,
    )
    response.raise_for_status()
    return SkillBulkResponse.model_validate(response.json())


def _set_group_install_setting(
    skill_id: UUID,
    group_id: int,
    permission: SkillSharePermission | None,
    policy: PluginInstallationPolicy,
) -> None:
    with get_session_with_current_tenant() as db_session:
        stmt = insert(Plugin__UserGroup).values(
            plugin_id=skill_id,
            user_group_id=group_id,
            permission=permission,
            installation_policy=policy,
        )
        db_session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    Plugin__UserGroup.plugin_id,
                    Plugin__UserGroup.user_group_id,
                ],
                set_={"installation_policy": policy},
            )
        )
        db_session.commit()


def _group_rows(
    skill_id: UUID,
) -> dict[int, tuple[SkillSharePermission | None, PluginInstallationPolicy | None]]:
    with get_session_with_current_tenant() as db_session:
        return {
            group_id: (permission, policy)
            for group_id, permission, policy in db_session.execute(
                select(
                    Plugin__UserGroup.user_group_id,
                    Plugin__UserGroup.permission,
                    Plugin__UserGroup.installation_policy,
                ).where(Plugin__UserGroup.plugin_id == skill_id)
            )
        }


def _company_settings(skill_id: UUID) -> tuple[str | None, str]:
    """The plugin's own setting and the legacy skill setting."""
    with get_session_with_current_tenant() as db_session:
        plugin_policy = db_session.scalar(
            select(Plugin.installation_policy).where(Plugin.id == skill_id)
        )
        legacy_policy = db_session.scalar(
            select(Skill.installation_policy).where(Skill.id == skill_id)
        )
        assert legacy_policy is not None
        return (
            plugin_policy.value if plugin_policy is not None else None,
            legacy_policy.value,
        )


def _assert_rows_match(*skill_ids: UUID) -> None:
    with get_session_with_current_tenant() as db_session:
        assert plugin_access_mismatches(db_session, skill_ids) == []


# --- Group install settings ------------------------------------------------


def test_bulk_share_keeps_group_install_setting(admin_user: DATestUser) -> None:
    skill = SkillManager.create_custom(admin_user, name=unique_name("keep-setting"))
    setting_group = _group(admin_user)
    share_group = _group(admin_user)
    # A row that holds only a group install setting.
    _set_group_install_setting(
        skill.id, setting_group.id, None, PluginInstallationPolicy.DEFAULT
    )

    result = _bulk_share(
        admin_user,
        [skill.id],
        {"group_shares": [{"group_id": share_group.id, "permission": "VIEWER"}]},
    )

    assert result.failed == []
    assert _group_rows(skill.id) == {
        setting_group.id: (None, PluginInstallationPolicy.DEFAULT),
        share_group.id: (SkillSharePermission.VIEWER, None),
    }
    _assert_rows_match(skill.id)


def test_share_keeps_group_install_setting_of_removed_share(
    admin_user: DATestUser,
) -> None:
    skill = SkillManager.create_custom(admin_user, name=unique_name("keep-removed"))
    group = _group(admin_user)
    share_skill(
        admin_user,
        skill.id,
        {"group_shares": [{"group_id": group.id, "permission": "EDITOR"}]},
    ).raise_for_status()
    _set_group_install_setting(
        skill.id,
        group.id,
        SkillSharePermission.EDITOR,
        PluginInstallationPolicy.DEFAULT,
    )

    # A level change keeps the setting.
    share_skill(
        admin_user,
        skill.id,
        {"group_shares": [{"group_id": group.id, "permission": "VIEWER"}]},
    ).raise_for_status()
    assert _group_rows(skill.id) == {
        group.id: (SkillSharePermission.VIEWER, PluginInstallationPolicy.DEFAULT)
    }

    # Removing the share keeps the setting, with no access.
    share_skill(admin_user, skill.id, {"group_shares": []}).raise_for_status()
    assert _group_rows(skill.id) == {group.id: (None, PluginInstallationPolicy.DEFAULT)}
    _assert_rows_match(skill.id)


# --- Group managers ----------------------------------------------------------


@pytest.fixture
def manager_env(
    admin_user: DATestUser,
) -> tuple[DATestUser, DATestUserGroup, DATestUserGroup]:
    manager = UserManager.create(name=unique_name("skill_manager"))
    managed = _group(admin_user, [manager.id])
    other = _group(admin_user)
    promote_to_manager(manager.id, managed.id)
    return manager, managed, other


def test_group_manager_is_refused_outside_their_groups(
    manager_env: tuple[DATestUser, DATestUserGroup, DATestUserGroup],
) -> None:
    manager, managed, other = manager_env
    skills = [
        SkillManager.create_custom(
            manager, name=unique_name("scoped"), group_ids=[managed.id]
        )
        for _ in range(2)
    ]
    outside = {"group_shares": [{"group_id": other.id, "permission": "VIEWER"}]}

    single = share_skill(manager, skills[0].id, outside)
    assert single.status_code == 403

    result = _bulk_share(manager, [skill.id for skill in skills], outside)
    assert result.succeeded == []
    assert {failure.skill_id for failure in result.failed} == {
        skill.id for skill in skills
    }
    for skill in skills:
        assert set(_group_rows(skill.id)) == {managed.id}

    # Inside their groups, the change goes through.
    inside = {"group_shares": [{"group_id": managed.id, "permission": "EDITOR"}]}
    share_skill(manager, skills[0].id, inside).raise_for_status()
    assert _group_rows(skills[0].id) == {
        managed.id: (SkillSharePermission.EDITOR, None)
    }


def test_group_manager_is_refused_install_settings(
    manager_env: tuple[DATestUser, DATestUserGroup, DATestUserGroup],
) -> None:
    """A group manager shares within their groups, but only an
    organization-wide skill manager sets a company or group install setting."""
    manager, managed, _other = manager_env
    skill = SkillManager.create_custom(
        manager, name=unique_name("scoped-policy"), group_ids=[managed.id]
    )

    single = share_skill(manager, skill.id, {"installation_policy": "DEFAULT"})
    assert single.status_code == 403
    group_setting = share_skill(
        manager,
        skill.id,
        {
            "group_settings": [
                {"group_id": managed.id, "installation_policy": "REQUIRED"}
            ]
        },
    )
    assert group_setting.status_code == 403
    assert _group_rows(skill.id) == {managed.id: (SkillSharePermission.VIEWER, None)}

    result = _bulk_share(manager, [skill.id], {"installation_policy": "REQUIRED"})
    assert [failure.skill_id for failure in result.failed] == [skill.id]
    assert _company_settings(skill.id) == (None, "AVAILABLE")


# --- Shares and the company install setting --------------------------------


def test_share_on_a_skill_writes_the_grant_on_its_plugin(
    admin_user: DATestUser, basic_user: DATestUser
) -> None:
    skill = SkillManager.create_custom(admin_user, name=unique_name("grant"))
    group = _group(admin_user)

    share_skill(
        admin_user,
        skill.id,
        {
            "user_shares": [{"user_id": basic_user.id, "permission": "EDITOR"}],
            "group_shares": [{"group_id": group.id, "permission": "VIEWER"}],
        },
    ).raise_for_status()

    with get_session_with_current_tenant() as db_session:
        user_grants = dict(
            db_session.execute(
                select(Plugin__User.user_id, Plugin__User.permission).where(
                    Plugin__User.plugin_id == skill.id
                )
            )
            .tuples()
            .all()
        )
    assert user_grants == {UUID(basic_user.id): SkillSharePermission.EDITOR}
    assert _group_rows(skill.id) == {group.id: (SkillSharePermission.VIEWER, None)}
    _assert_rows_match(skill.id)


def test_admin_changes_the_company_install_setting(admin_user: DATestUser) -> None:
    single = SkillManager.create_custom(admin_user, name=unique_name("company"))
    bulk = SkillManager.create_custom(admin_user, name=unique_name("company-bulk"))

    # A value sets it.
    share_skill(
        admin_user, single.id, {"installation_policy": "REQUIRED"}
    ).raise_for_status()
    result = _bulk_share(admin_user, [bulk.id], {"installation_policy": "DEFAULT"})
    assert result.failed == []
    assert _company_settings(single.id) == ("REQUIRED", "REQUIRED")
    assert _company_settings(bulk.id) == ("DEFAULT", "DEFAULT")

    # A missing setting changes nothing.
    share_skill(admin_user, single.id, {"user_shares": []}).raise_for_status()
    result = _bulk_share(admin_user, [bulk.id], {"user_shares": []})
    assert result.failed == []
    assert _company_settings(single.id) == ("REQUIRED", "REQUIRED")
    assert _company_settings(bulk.id) == ("DEFAULT", "DEFAULT")

    # An explicit null takes the marketplace default.
    share_skill(admin_user, single.id, {"installation_policy": None}).raise_for_status()
    result = _bulk_share(admin_user, [bulk.id], {"installation_policy": None})
    assert result.failed == []
    assert _company_settings(single.id) == (None, "AVAILABLE")
    assert _company_settings(bulk.id) == (None, "AVAILABLE")
    _assert_rows_match(single.id, bulk.id)
