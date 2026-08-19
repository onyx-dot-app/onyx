"""
DB operations for recomputing user effective_permissions.

These live in onyx/db/ (not onyx/auth/) because they are pure DB operations
that query PermissionGrant rows and update the User.effective_permissions
JSONB column.  Keeping them here avoids circular imports when called from
other onyx/db/ modules such as users.py.
"""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import AccountType, Permission
from onyx.db.models import PermissionGrant, User, User__UserGroup
from onyx.utils.logger import setup_logger

logger = setup_logger()


def parse_permission_values(values: Iterable[str]) -> list[Permission]:
    """Parse stored permission strings into Permissions, dropping unknown values.

    Stored values are validated on write, so an unknown one means stale/corrupt
    data; we drop it (logged) rather than fail the read — dropping only ever
    narrows access, so it fails safe.
    """
    parsed: list[Permission] = []
    for value in values:
        try:
            parsed.append(Permission(value))
        except ValueError:
            logger.warning("Ignoring unknown permission value %r", value)
    return parsed


def account_derived_permissions(
    account_type: AccountType, in_any_group: bool
) -> set[str]:
    """Permissions a user holds by virtue of what they are, independent of group
    grants. A service account in no group is the "limited" case — it has no grants
    to draw chat scope from, so give it the write scope directly (WRITE_CHAT
    implies READ_CHAT at read time)."""
    if account_type == AccountType.SERVICE_ACCOUNT and not in_any_group:
        return {Permission.WRITE_CHAT.value}
    return set()


def recompute_user_permissions__no_commit(
    user_ids: UUID | str | list[UUID] | list[str], db_session: Session
) -> None:
    """Recompute granted permissions for one or more users: group grants
    plus role-derived permissions. Implication expansion happens at read
    time via get_effective_permissions().

    Accepts a single UUID or a list.  Uses a single query regardless of
    how many users are passed, avoiding N+1 issues.

    Stores only directly granted permissions — implication expansion
    happens at read time via get_effective_permissions().

    Also refreshes the cached ``is_group_manager`` flag in the same write.

    Does NOT commit — caller must commit the session.
    """
    if isinstance(user_ids, (UUID, str)):
        raw_ids: list[UUID | str] = [user_ids]
    else:
        raw_ids = list(user_ids)

    if not raw_ids:
        return

    # Normalize up front: the lookups below key on str(id), so a valid but non-canonical
    # string ("6F89..." / unhyphenated) would miss them even though Postgres matches it.
    uid_list: list[UUID] = [
        uid if isinstance(uid, UUID) else UUID(str(uid)) for uid in raw_ids
    ]

    # Single query to fetch ALL permissions for these users across ALL their
    # groups (a user may belong to multiple groups with different grants).
    rows = db_session.execute(
        select(User__UserGroup.user_id, PermissionGrant.permission)
        .join(
            PermissionGrant,
            PermissionGrant.group_id == User__UserGroup.user_group_id,
        )
        .where(
            User__UserGroup.user_id.in_(uid_list),
            PermissionGrant.is_deleted.is_(False),
        )
    ).all()

    # Membership, not grants: a group that grants nothing still means "not limited".
    grouped_user_ids = {
        str(uid).lower()
        for (uid,) in db_session.execute(
            select(User__UserGroup.user_id)
            .where(User__UserGroup.user_id.in_(uid_list))
            .distinct()
        ).all()
        if uid is not None
    }

    role_derived_by_user: dict[str, set[str]] = {
        str(user_id).lower(): account_derived_permissions(
            account_type, str(user_id).lower() in grouped_user_ids
        )
        for user_id, account_type in db_session.execute(
            select(User.id, User.account_type).where(  # ty: ignore[no-matching-overload]
                User.id.in_(uid_list)  # ty: ignore[unresolved-attribute]
            )
        ).all()
    }

    # Group permissions by user; users with no grants get an empty set.
    perms_by_user: dict[UUID, set[str]] = defaultdict(set)
    for uid in uid_list:
        perms_by_user[uid]  # ensure every user has an entry
    for uid, perm in rows:
        perms_by_user[uid].add(perm.value)

    # Cache only the boolean; the managed-group list stays live. Keyed by str
    # so the membership check holds whether callers pass UUID or str user ids.
    manager_uids: set[str] = {
        str(uid)
        for uid in db_session.scalars(
            select(User__UserGroup.user_id)
            .where(
                User__UserGroup.user_id.in_(uid_list),
                User__UserGroup.is_manager.is_(True),
            )
            .distinct()
        )
        if uid is not None
    }

    for uid, perms in perms_by_user.items():
        perms |= role_derived_by_user.get(str(uid).lower(), set())
        db_session.execute(
            update(User)
            .where(User.id == uid)  # ty: ignore[invalid-argument-type]
            .values(
                effective_permissions=sorted(perms),
                is_group_manager=str(uid) in manager_uids,
            )
        )


def recompute_permissions_for_group__no_commit(
    group_id: int, db_session: Session
) -> None:
    """Recompute granted permissions for all users in a group.

    Does NOT commit — caller must commit the session.
    """
    user_ids: list[UUID] = [
        uid
        for uid in db_session.execute(
            select(User__UserGroup.user_id).where(
                User__UserGroup.user_group_id == group_id,
                User__UserGroup.user_id.isnot(None),
            )
        )
        .scalars()
        .all()
        if uid is not None
    ]

    if not user_ids:
        return

    recompute_user_permissions__no_commit(user_ids, db_session)
