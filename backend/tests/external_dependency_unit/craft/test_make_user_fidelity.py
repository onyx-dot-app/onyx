"""``make_user`` must derive authority the way production does.

``effective_permissions`` is a cache column and the authorization read path
never joins the group tables, so a fixture can hand-write any value and every
permission check will believe it. These tests pin the helper to the real
default-group grants, so a hard-coded permission list fails here instead of
drifting silently.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import AccountType, Permission
from onyx.db.models import PermissionGrant, User__UserGroup, UserGroup
from onyx.db.users import DEFAULT_ADMIN_GROUP_NAME, DEFAULT_BASIC_GROUP_NAME
from tests.external_dependency_unit.craft.db_helpers import make_user


def _default_group_grants(db_session: Session, group_name: str) -> set[str]:
    return {
        permission.value
        for permission in db_session.scalars(
            select(PermissionGrant.permission)
            .join(UserGroup, UserGroup.id == PermissionGrant.group_id)
            .where(
                UserGroup.name == group_name,
                UserGroup.is_default.is_(True),
                PermissionGrant.is_deleted.is_(False),
            )
        )
    }


def _group_names(db_session: Session, user_id: UUID) -> set[str]:
    return set(
        db_session.scalars(
            select(UserGroup.name)
            .join(User__UserGroup, User__UserGroup.user_group_id == UserGroup.id)
            .where(User__UserGroup.user_id == user_id)
        )
    )


def test_standard_user_permissions_come_from_the_basic_group(
    db_session: Session,
) -> None:
    user = make_user(db_session, standard_account=True)

    assert DEFAULT_BASIC_GROUP_NAME in _group_names(db_session, user.id)
    assert set(user.effective_permissions) == _default_group_grants(
        db_session, DEFAULT_BASIC_GROUP_NAME
    )


def test_admin_user_joins_the_admin_group(db_session: Session) -> None:
    user = make_user(db_session, is_admin=True)

    assert DEFAULT_ADMIN_GROUP_NAME in _group_names(db_session, user.id)
    assert set(user.effective_permissions) == _default_group_grants(
        db_session, DEFAULT_ADMIN_GROUP_NAME
    )
    assert Permission.FULL_ADMIN_PANEL_ACCESS.value in user.effective_permissions


def test_group_manager_flag_is_backed_by_a_manager_edge(db_session: Session) -> None:
    user = make_user(db_session, is_group_manager=True)

    assert user.is_group_manager is True
    managed = db_session.scalars(
        select(User__UserGroup.user_group_id).where(
            User__UserGroup.user_id == user.id,
            User__UserGroup.is_manager.is_(True),
        )
    ).all()
    assert len(managed) == 1


def test_default_user_is_a_group_less_placeholder(db_session: Session) -> None:
    """This is the row production's ``_generate_ext_permissioned_user`` builds."""
    user = make_user(db_session)

    assert user.account_type == AccountType.EXT_PERM_USER
    assert _group_names(db_session, user.id) == set()
    assert user.effective_permissions == []
