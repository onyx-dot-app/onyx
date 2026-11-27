"""Rules of the one access change function for group install settings and
group shares."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import (
    PluginInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    Plugin__User,
    Plugin__UserGroup,
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
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
)
from onyx.db.skill import fetch_editable_skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
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
            fetch_editable_skill(
                skill.id,
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


def test_not_available_writes(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Not available is accepted as the company setting and as a group
    setting with no share."""
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
    assert skill.installation_policy == PluginInstallationPolicy.NOT_AVAILABLE
    row = _group_row(db_session, skill.id, group)
    assert row is not None
    assert row.permission is None
    assert row.installation_policy == PluginInstallationPolicy.NOT_AVAILABLE


def test_scoped_manager_user_shares_stay_within_managed_groups(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """A scoped manager cannot share a plugin they reach only through their
    groups with a user outside those groups. The author can, also in the same
    bulk change, and the manager can still add and remove member shares."""
    group = make_group(db_session)
    manager = _manager_of(db_session, group)
    member = make_user(db_session, standard_account=True)
    add_user_to_group(db_session, member, group)
    outsider = make_user(db_session, standard_account=True)
    author = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=author.id)
    share_plugin_with_group(db_session, skill.id, group.id, SkillSharePermission.VIEWER)

    def user_shares(*users: User) -> PluginAccessChange:
        return PluginAccessChange(
            user_grants=tuple(
                PluginUserGrant(user_id=user.id, permission=SkillSharePermission.VIEWER)
                for user in users
            ),
            mode=PluginAccessMode.REPLACE,
        )

    def shared_user_ids() -> set[object]:
        return set(
            db_session.scalars(
                select(Plugin__User.user_id).where(Plugin__User.plugin_id == skill.id)
            )
        )

    with pytest.raises(OnyxError) as exc_info:
        apply_plugin_access_change__no_commit(
            [skill.id], user_shares(member, outsider), manager, db_session
        ).raise_first_failure()
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert shared_user_ids() == set()

    apply_plugin_access_change__no_commit(
        [skill.id], user_shares(member), manager, db_session
    ).raise_first_failure()
    assert shared_user_ids() == {member.id}
    apply_plugin_access_change__no_commit(
        [skill.id], user_shares(), manager, db_session
    ).raise_first_failure()
    assert shared_user_ids() == set()

    own_skill = make_skill(db_session, author_user_id=manager.id)
    share_plugin_with_group(
        db_session, own_skill.id, group.id, SkillSharePermission.VIEWER
    )
    result = apply_plugin_access_change__no_commit(
        [skill.id, own_skill.id], user_shares(outsider), manager, db_session
    )
    assert set(result.failures) == {skill.id}
    assert shared_user_ids() == set()
    assert set(
        db_session.scalars(
            select(Plugin__User.user_id).where(Plugin__User.plugin_id == own_skill.id)
        )
    ) == {outsider.id}


def test_scoped_manager_cannot_lift_the_member_rule_with_self_granted_editor(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Editor rights that a scoped manager can grant to themselves do not let
    them share with a user outside their groups. A managed group's editor share
    on a published skill, which they cannot grant, does."""
    group = make_group(db_session)
    manager = _manager_of(db_session, group)
    outsider = make_user(db_session, standard_account=True)
    author = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=author.id)
    share_plugin_with_group(db_session, skill.id, group.id, SkillSharePermission.VIEWER)

    def share_with(user: User, permission: SkillSharePermission) -> None:
        apply_plugin_access_change__no_commit(
            [skill.id],
            PluginAccessChange(
                user_grants=(PluginUserGrant(user_id=user.id, permission=permission),),
                mode=PluginAccessMode.ADD_ONLY,
            ),
            manager,
            db_session,
        ).raise_first_failure()

    with pytest.raises(OnyxError) as exc_info:
        share_with(manager, SkillSharePermission.EDITOR)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert (
        db_session.scalar(
            select(Plugin__User.user_id).where(Plugin__User.plugin_id == skill.id)
        )
        is None
    )

    apply_plugin_access_change__no_commit(
        [skill.id],
        PluginAccessChange(
            group_grants=(
                PluginGroupGrant(
                    group_id=group.id, permission=SkillSharePermission.EDITOR
                ),
            ),
            mode=PluginAccessMode.ADD_ONLY,
        ),
        manager,
        db_session,
    ).raise_first_failure()
    with pytest.raises(OnyxError) as exc_info:
        share_with(outsider, SkillSharePermission.VIEWER)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    share_plugin_with_user(
        db_session, skill.id, manager.id, SkillSharePermission.EDITOR
    )
    share_with(outsider, SkillSharePermission.VIEWER)

    published = make_skill(db_session, is_public=True, author_user_id=author.id)
    share_plugin_with_group(
        db_session, published.id, group.id, SkillSharePermission.EDITOR
    )
    apply_plugin_access_change__no_commit(
        [published.id],
        PluginAccessChange(
            user_grants=(
                PluginUserGrant(
                    user_id=outsider.id, permission=SkillSharePermission.VIEWER
                ),
            ),
            mode=PluginAccessMode.ADD_ONLY,
        ),
        manager,
        db_session,
    ).raise_first_failure()


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
