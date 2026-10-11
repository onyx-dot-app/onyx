"""Migration b6d920407aa6 grants create:user_api_keys to the Basic group and
backfills its members' stored permissions. The test database already sits at
head, so the test runs downgrade then upgrade inside its transaction and
rolls back."""

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.enums import GrantSource, Permission
from onyx.db.models import PermissionGrant, User, User__UserGroup, UserGroup
from onyx.db.users import DEFAULT_BASIC_GROUP_NAME

_MIGRATION_PATH = (
    Path(__file__).parents[3]
    / "alembic/versions/b6d920407aa6_grant_create_pat_to_basic_group.py"
)
PAT_PERMISSION = Permission.CREATE_USER_API_KEYS.value
BASIC_PERMISSION = Permission.BASIC_ACCESS.value


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "pat_grant_migration", _MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _basic_grant(db_session: Session, basic: UserGroup) -> PermissionGrant | None:
    return db_session.scalar(
        select(PermissionGrant).where(
            PermissionGrant.group_id == basic.id,
            PermissionGrant.permission == Permission.CREATE_USER_API_KEYS,
        )
    )


def _stored_permissions(db_session: Session, user: User) -> set[str]:
    db_session.expire(user)
    return set(user.effective_permissions)


def _make_user(db_session: Session, permissions: list[str]) -> User:
    user = User(
        id=uuid4(),
        email=f"pat-migration-{uuid4().hex[:8]}@example.com",
        hashed_password="unused",
        effective_permissions=permissions,
    )
    db_session.add(user)
    return user


def test_basic_members_lose_and_regain_the_grant(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    try:
        basic: UserGroup | None = db_session.scalar(
            select(UserGroup).where(
                UserGroup.name == DEFAULT_BASIC_GROUP_NAME,
                UserGroup.is_default.is_(True),
            )
        )
        assert basic is not None

        other_group = UserGroup(name=f"pat-migration-{uuid4().hex[:8]}")
        db_session.add(other_group)
        db_session.flush()
        db_session.add(
            PermissionGrant(
                group_id=other_group.id,
                permission=Permission.CREATE_USER_API_KEYS,
                grant_source=GrantSource.USER,
            )
        )

        member: User = _make_user(db_session, [BASIC_PERMISSION, PAT_PERMISSION])
        dual: User = _make_user(db_session, [BASIC_PERMISSION, PAT_PERMISSION])
        outsider: User = _make_user(db_session, [])
        db_session.flush()
        db_session.add_all(
            [
                User__UserGroup(user_group_id=basic.id, user_id=member.id),
                User__UserGroup(user_group_id=basic.id, user_id=dual.id),
                User__UserGroup(user_group_id=other_group.id, user_id=dual.id),
            ]
        )
        db_session.flush()

        migration: ModuleType = _load_migration()
        with Operations.context(MigrationContext.configure(db_session.connection())):
            migration.downgrade()
            assert _basic_grant(db_session, basic) is None
            assert _stored_permissions(db_session, member) == {BASIC_PERMISSION}
            # Held through the other group, so the downgrade leaves it alone.
            assert _stored_permissions(db_session, dual) == {
                BASIC_PERMISSION,
                PAT_PERMISSION,
            }
            assert _stored_permissions(db_session, outsider) == set()

            migration.upgrade()
            grant: PermissionGrant | None = _basic_grant(db_session, basic)
            assert grant is not None
            assert grant.grant_source == GrantSource.SYSTEM
            assert not grant.is_deleted
            assert _stored_permissions(db_session, member) == {
                BASIC_PERMISSION,
                PAT_PERMISSION,
            }
            db_session.expire(dual)
            assert sorted(dual.effective_permissions) == [
                BASIC_PERMISSION,
                PAT_PERMISSION,
            ]
            assert _stored_permissions(db_session, outsider) == set()

            # A soft-deleted Basic grant is revived rather than duplicated.
            grant.is_deleted = True
            member.effective_permissions = [BASIC_PERMISSION]
            db_session.flush()
            migration.upgrade()
            db_session.expire(grant)
            assert not grant.is_deleted
            assert PAT_PERMISSION in _stored_permissions(db_session, member)
    finally:
        db_session.rollback()
