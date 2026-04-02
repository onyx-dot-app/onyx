"""
DB operations for recomputing user effective_permissions.

These live in onyx/db/ (not onyx/auth/) because they are pure DB operations
that query PermissionGrant rows and update the User.effective_permissions
JSONB column.  Keeping them here avoids circular imports when called from
other onyx/db/ modules such as users.py.
"""

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.models import PermissionGrant
from onyx.db.models import User
from onyx.db.models import User__UserGroup


def recompute_user_permissions__no_commit(
    user_ids: UUID | str | list[UUID] | list[str], db_session: Session
) -> None:
    """Recompute granted permissions for one or more users.

    Accepts a single UUID or a list.  Uses a single query regardless of
    how many users are passed, avoiding N+1 issues.

    Stores only directly granted permissions — implication expansion
    happens at read time via get_effective_permissions().

    Does NOT commit — caller must commit the session.
    """
    if isinstance(user_ids, (UUID, str)):
        uid_list = [user_ids]
    else:
        uid_list = list(user_ids)

    if not uid_list:
        return

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

    # Group permissions by user; users with no grants get an empty set.
    perms_by_user: dict[UUID, set[str]] = defaultdict(set)
    for uid in uid_list:
        perms_by_user[uid]  # ensure every user has an entry
    for uid, perm in rows:
        perms_by_user[uid].add(perm.value)

    for uid, perms in perms_by_user.items():
        db_session.execute(
            update(User)
            .where(User.id == uid)  # type: ignore[arg-type]
            .values(effective_permissions=sorted(perms))
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
