"""Rules of the one access change function for group install settings, group
shares and the admin Sharing setting."""

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
    PluginUserGrant,
    apply_plugin_access_change__no_commit,
)
from onyx.db.skill import SkillManagementPolicy, fetch_skill
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import Settings
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
        group_grants=(
            PluginGroupGrant(
                group_id=group.id, permission=permission, installation_policy=policy
            ),
        ),
        mode=PluginAccessMode.ADD_ONLY,
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
        ("manager", False, None),
        # A published plugin needs organization-wide MANAGE_PLUGINS (H6).
        ("manager", True, OnyxErrorCode.INSUFFICIENT_PERMISSIONS),
        # A manager of another group.
        ("other_manager", False, OnyxErrorCode.INSUFFICIENT_PERMISSIONS),
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
    elif actor_kind == "manager":
        actor = _manager_of(db_session, group)
    else:
        actor = _manager_of(db_session, make_group(db_session))
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


@pytest.mark.parametrize("outside", ["group", "user"])
def test_scoped_manager_cannot_set_a_group_setting_on_a_plugin_shared_outside(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    outside: str,
) -> None:
    """H6 and R17: the plugin must be shared only within the manager's groups,
    by group share and by direct user share."""
    group = make_group(db_session)
    manager = _manager_of(db_session, group)
    skill = make_skill(db_session, author_user_id=manager.id)
    if outside == "group":
        share_plugin_with_group(
            db_session, skill.id, make_group(db_session).id, SkillSharePermission.VIEWER
        )
    else:
        share_plugin_with_user(
            db_session,
            skill.id,
            make_user(db_session, standard_account=True).id,
            SkillSharePermission.VIEWER,
        )

    with pytest.raises(OnyxError) as exc_info:
        apply_plugin_access_change__no_commit(
            [skill.id], _setting_for(group), manager, db_session
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    assert "outside the groups you manage" in exc_info.value.detail

    # A direct share with a member of the managed group stays in scope.
    if outside == "user":
        member = make_user(db_session, standard_account=True)
        add_user_to_group(db_session, member, group)
        apply_plugin_access_change__no_commit(
            [skill.id],
            PluginAccessChange(
                user_grants=(
                    PluginUserGrant(
                        user_id=member.id, permission=SkillSharePermission.VIEWER
                    ),
                ),
                group_grants=_setting_for(group).group_grants,
            ),
            manager,
            db_session,
        ).raise_first_failure()


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


def test_editor_with_not_available_is_refused(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    admin = make_user(db_session, is_admin=True)
    group = make_group(db_session)
    skill = make_skill(db_session, author_user_id=admin.id)

    with pytest.raises(OnyxError) as exc_info:
        apply_plugin_access_change__no_commit(
            [skill.id],
            _setting_for(
                group,
                PluginInstallationPolicy.NOT_AVAILABLE,
                SkillSharePermission.EDITOR,
            ),
            admin,
            db_session,
        )
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT

    # The existing setting counts too.
    share_plugin_with_group(
        db_session,
        skill.id,
        group.id,
        SkillSharePermission.VIEWER,
        PluginInstallationPolicy.NOT_AVAILABLE,
    )
    with pytest.raises(OnyxError):
        apply_plugin_access_change__no_commit(
            [skill.id],
            PluginAccessChange(
                group_grants=(
                    PluginGroupGrant(
                        group_id=group.id, permission=SkillSharePermission.EDITOR
                    ),
                ),
            ),
            admin,
            db_session,
        )


def test_not_available_writes_and_the_legacy_rows(
    db_session: Session,
    test_user: User,  # noqa: ARG001
) -> None:
    """Not available is accepted. The legacy column gets AVAILABLE, and a
    group row with Not available gets no legacy share."""
    admin = make_user(db_session, is_admin=True)
    group = make_group(db_session)
    skill = make_skill(db_session, author_user_id=admin.id)

    apply_plugin_access_change__no_commit(
        [skill.id],
        PluginAccessChange(
            company_installation_policy=PluginInstallationPolicy.NOT_AVAILABLE,
            group_grants=_setting_for(
                group, PluginInstallationPolicy.NOT_AVAILABLE
            ).group_grants,
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

    member_owner = make_user(db_session, standard_account=True)
    other = make_skill(db_session, author_user_id=member_owner.id)
    with pytest.raises(OnyxError) as exc_info:
        apply_plugin_access_change__no_commit(
            [other.id], _setting_for(group, None), member_owner, db_session
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_member_share_is_refused_while_sharing_is_off(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "onyx.db.plugin.load_settings",
        lambda raise_on_error=False: Settings(plugin_sharing=False),  # noqa: ARG005
    )
    owner = make_user(db_session, standard_account=True)
    admin = make_user(db_session, is_admin=True)
    viewer = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    share = PluginAccessChange(
        user_grants=(
            PluginUserGrant(user_id=viewer.id, permission=SkillSharePermission.VIEWER),
        )
    )

    with pytest.raises(OnyxError) as exc_info:
        apply_plugin_access_change__no_commit([skill.id], share, owner, db_session)
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    # An organization-wide manager still shares, and the owner can remove it.
    apply_plugin_access_change__no_commit(
        [skill.id], share, admin, db_session
    ).raise_first_failure()
    apply_plugin_access_change__no_commit(
        [skill.id], PluginAccessChange(user_grants=()), owner, db_session
    ).raise_first_failure()
