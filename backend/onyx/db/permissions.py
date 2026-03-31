"""
DB operations for recomputing user effective_permissions.

These live in onyx/db/ (not onyx/auth/) because they are pure DB operations
that query PermissionGrant rows and update the User.effective_permissions
JSONB column.  Keeping them here avoids circular imports when called from
other onyx/db/ modules such as users.py.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.models import PermissionGrant
from onyx.db.models import User
from onyx.db.models import User__UserGroup


def recompute_user_permissions__no_commit(user_id: UUID, db_session: Session) -> None:
    """Recompute a single user's granted permissions from their group grants.

    Stores only directly granted permissions — implication expansion
    happens at read time via get_effective_permissions().

    Does NOT commit — caller must commit the session.
    """
    stmt = (
        select(PermissionGrant.permission)
        .join(
            User__UserGroup,
            PermissionGrant.group_id == User__UserGroup.user_group_id,
        )
        .where(
            User__UserGroup.user_id == user_id,
            PermissionGrant.is_deleted.is_(False),
        )
    )
    rows = db_session.execute(stmt).scalars().all()
    # sorted for consistent ordering in DB — easier to read when debugging
    granted = sorted({p.value for p in rows})

    db_session.execute(
        update(User).where(User.id == user_id).values(effective_permissions=granted)
    )


def recompute_permissions_for_group__no_commit(
    group_id: int, db_session: Session
) -> None:
    """Recompute granted permissions for all users in a group.

    Does NOT commit — caller must commit the session.
    """
    user_ids = (
        db_session.execute(
            select(User__UserGroup.user_id).where(
                User__UserGroup.user_group_id == group_id,
                User__UserGroup.user_id.isnot(None),
            )
        )
        .scalars()
        .all()
    )
    for uid in user_ids:
        recompute_user_permissions__no_commit(uid, db_session)
