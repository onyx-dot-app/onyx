"""Group install setting rules of the one access change function. The skills
API cannot send a group install setting, so these tests call the function."""

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import PluginInstallationPolicy, SkillSharePermission
from onyx.db.models import User, User__UserGroup, UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.plugin import (
    PluginAccessChange,
    PluginGroupGrant,
    apply_plugin_access_change__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_skill,
    make_user,
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


def _setting_for(group: UserGroup) -> PluginAccessChange:
    return PluginAccessChange(
        group_grants=(
            PluginGroupGrant(
                group_id=group.id,
                permission=SkillSharePermission.VIEWER,
                installation_policy=PluginInstallationPolicy.DEFAULT,
            ),
        )
    )


@pytest.mark.parametrize(
    ("actor_kind", "published", "expected"),
    [
        # Allowed by the permission rule, then refused until group settings ship.
        ("admin", False, OnyxErrorCode.INVALID_INPUT),
        ("admin", True, OnyxErrorCode.INVALID_INPUT),
        ("manager", False, OnyxErrorCode.INVALID_INPUT),
        # A published plugin needs organization-wide MANAGE_SKILLS.
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
    expected: OnyxErrorCode,
) -> None:
    group = make_group(db_session)
    if actor_kind == "admin":
        actor = make_user(db_session, is_admin=True)
    elif actor_kind == "manager":
        actor = _manager_of(db_session, group)
    else:
        actor = _manager_of(db_session, make_group(db_session))
    skill = make_skill(db_session, is_public=published, author_user_id=actor.id)

    with pytest.raises(OnyxError) as exc_info:
        apply_plugin_access_change__no_commit(
            [skill.id], _setting_for(group), actor, db_session
        )
    assert exc_info.value.error_code == expected
