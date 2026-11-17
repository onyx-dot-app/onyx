"""Rules of the one access change function for group install settings and
group shares."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    PluginInstallationPolicy,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    Plugin__UserGroup,
    Skill__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.plugin import (
    PluginAccessChange,
    PluginAccessMode,
    PluginGroupGrant,
    PluginGroupSetting,
    apply_plugin_access_change__no_commit,
)
from onyx.db.skill import SkillManagementPolicy, fetch_skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_skill,
    make_user,
    share_plugin_with_group,
    share_plugin_with_user,
)


def _manager_of(db_session: Session, group: UserGroup) -> User:
    manager = make_user(db_session, is_group_manager=True)
    db_session.add(
        User__UserGroup(user_id=manager.id, user_group_id=group.id, is_manager=True)
    )
    db_session.flush()
    recompute_user_permissions__no_commit(manager.id, db_session)
    db_session.refresh(manager)
    return manager


def _setting_for(
    group: UserGroup,
    policy: PluginInstallationPolicy | None = PluginInstallationPolicy.DEFAULT,
    permission: SkillSharePermission = SkillSharePermission.VIEWER,
) -> PluginAccessChange:
    return PluginAccessChange(
        group_grants=(PluginGroupGrant(group_id=group.id, permission=permission),),
        group_settings=(
            PluginGroupSetting(group_id=group.id, installation_policy=policy),
        ),
        mode=PluginAccessMode.ADD_ONLY,
    )


def _group_setting(
    group: UserGroup, policy: PluginInstallationPolicy | None
) -> PluginAccessChange:
    return PluginAccessChange(
        group_settings=(
            PluginGroupSetting(group_id=group.id, installation_policy=policy),
        )
    )


def _group_row(
    db_session: Session, plugin_id: object, group: UserGroup
) -> Plugin__UserGroup | None:
    return db_session.scalar(
        select(Plugin__UserGroup).where(
            Plugin__UserGroup.plugin_id == plugin_id,
            Plugin__UserGroup.user_group_id == group.id,
        )
    )


@pytest.mark.parametrize(
    ("actor_kind", "published", "expected"),
    [
        ("admin", False, None),
        ("admin", True, None),
    ],
)
def test_group_install_setting_rules(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    actor_kind: str,
    published: bool,
    expected: OnyxErrorCode | None,
) -> None:
    group = make_group(db_session)
    if actor_kind == "admin":
        actor = make_user(db_session, is_admin=True)
    else:
        actor = _manager_of(db_session, group)
    skill = make_skill(db_session, is_public=published, author_user_id=actor.id)

    if expected is None:
        apply_plugin_access_change__no_commit(
            [skill.id], _setting_for(group), actor, db_session
        ).raise_first_failure()
        row = _group_row(db_session, skill.id, group)
        assert row is not None
        assert row.installation_policy == PluginInstallationPolicy.DEFAULT
        return
    with pytest.raises(OnyxError) as exc_info:
        apply_plugin_access_change__no_commit(
            [skill.id], _setting_for(group), actor, db_session
        )
    assert exc_info.value.error_code == expected


def test_scoped_manager_edit_scope_checks_direct_user_shares(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """R17: a scoped manager edits a plugin shared within their groups, but not
    one also shared directly with a user outside them."""
    group = make_group(db_session)
    manager = _manager_of(db_session, group)
    skill = make_skill(db_session)
    share_plugin_with_group(db_session, skill.id, group.id, SkillSharePermission.VIEWER)

    def editable() -> bool:
        return (
            fetch_skill(
                skill.id,
                policy=SkillManagementPolicy.EDIT,
                user=manager,
                db_session=db_session,
            )
            is not None
        )

    assert editable()
    share_plugin_with_user(
        db_session,
        skill.id,
        make_user(db_session, standard_account=True).id,
        SkillSharePermission.VIEWER,
    )
    assert not editable()


def test_not_available_writes_and_the_legacy_rows(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Not available is accepted. The legacy column gets AVAILABLE, and a
    group row with only a setting gets no legacy share."""
    admin = make_user(db_session, is_admin=True)
    group = make_group(db_session)
    skill = make_skill(db_session, author_user_id=admin.id)

    apply_plugin_access_change__no_commit(
        [skill.id],
        PluginAccessChange(
            company_installation_policy=PluginInstallationPolicy.NOT_AVAILABLE,
            group_settings=_group_setting(
                group, PluginInstallationPolicy.NOT_AVAILABLE
            ).group_settings,
        ),
        admin,
        db_session,
    ).raise_first_failure()

    db_session.refresh(skill)
    assert skill.installation_policy == SkillInstallationPolicy.AVAILABLE
    row = _group_row(db_session, skill.id, group)
    assert row is not None
    assert row.installation_policy == PluginInstallationPolicy.NOT_AVAILABLE
    assert (
        db_session.scalar(
            select(Skill__UserGroup).where(
                Skill__UserGroup.skill_id == skill.id,
                Skill__UserGroup.user_group_id == group.id,
            )
        )
        is None
    )


def test_owner_removing_a_group_share_keeps_its_setting(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """An owner who removes a group share clears the permission only; the
    group's install setting stays. Only MANAGE_PLUGINS changes the setting."""
    admin = make_user(db_session, is_admin=True)
    group = make_group(db_session)
    owner = _manager_of(db_session, group)
    skill = make_skill(db_session, author_user_id=owner.id)
    apply_plugin_access_change__no_commit(
        [skill.id], _setting_for(group), admin, db_session
    ).raise_first_failure()

    apply_plugin_access_change__no_commit(
        [skill.id], PluginAccessChange(group_grants=()), owner, db_session
    ).raise_first_failure()
    row = _group_row(db_session, skill.id, group)
    assert row is not None
    assert row.permission is None
    assert row.installation_policy == PluginInstallationPolicy.DEFAULT
