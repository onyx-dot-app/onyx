"""
Permission resolution for group-based authorization.

Granted permissions are stored as a JSONB column on the User table and
loaded for free with every auth query. Implied permissions are expanded
at read time — only directly granted permissions are persisted.
"""

from collections.abc import Callable
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.enums import Permission
from onyx.db.models import PermissionGrant
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

ALL_PERMISSIONS: frozenset[str] = frozenset(p.value for p in Permission)

# Implication map: granted permission -> set of permissions it implies.
IMPLIES: dict[str, set[str]] = {
    Permission.ADD_AGENTS.value: {Permission.READ_AGENTS.value},
    Permission.MANAGE_AGENTS.value: {
        Permission.ADD_AGENTS.value,
        Permission.READ_AGENTS.value,
    },
    Permission.MANAGE_DOCUMENT_SETS.value: {
        Permission.READ_DOCUMENT_SETS.value,
        Permission.READ_CONNECTORS.value,
    },
    Permission.ADD_CONNECTORS.value: {Permission.READ_CONNECTORS.value},
    Permission.MANAGE_CONNECTORS.value: {
        Permission.ADD_CONNECTORS.value,
        Permission.READ_CONNECTORS.value,
    },
    Permission.MANAGE_USER_GROUPS.value: {
        Permission.READ_CONNECTORS.value,
        Permission.READ_DOCUMENT_SETS.value,
        Permission.READ_AGENTS.value,
        Permission.READ_USERS.value,
    },
}


def resolve_effective_permissions(granted: set[str]) -> set[str]:
    """Expand granted permissions with their implied permissions.

    If "admin" is present, returns all 19 permissions.
    """
    if Permission.FULL_ADMIN_PANEL_ACCESS.value in granted:
        return set(ALL_PERMISSIONS)

    effective = set(granted)
    changed = True
    while changed:
        changed = False
        for perm in list(effective):
            implied = IMPLIES.get(perm)
            if implied and not implied.issubset(effective):
                effective |= implied
                changed = True
    return effective


def get_effective_permissions(user: User) -> set[Permission]:
    """Read granted permissions from the column and expand implied permissions."""
    granted: set[Permission] = set()
    for p in user.effective_permissions:
        try:
            granted.add(Permission(p))
        except ValueError:
            logger.warning(f"Skipping unknown permission '{p}' for user {user.id}")
    if Permission.FULL_ADMIN_PANEL_ACCESS in granted:
        return set(Permission)
    expanded = resolve_effective_permissions({p.value for p in granted})
    return {Permission(p) for p in expanded}


def recompute_user_permissions(user_id: UUID, db_session: Session) -> None:
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


def recompute_permissions_for_group(group_id: int, db_session: Session) -> None:
    """Recompute granted permissions for all users in a group.

    Does NOT commit — caller must commit the session.
    """
    user_ids = (
        db_session.execute(
            select(User__UserGroup.user_id).where(
                User__UserGroup.user_group_id == group_id
            )
        )
        .scalars()
        .all()
    )
    for uid in user_ids:
        if uid is not None:
            recompute_user_permissions(uid, db_session)


def require_permission(
    required: Permission,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """FastAPI dependency factory for permission-based access control.

    Usage:
        @router.get("/endpoint")
        def endpoint(user: User = Depends(require_permission(Permission.MANAGE_CONNECTORS))):
            ...
    """

    async def dependency(user: User = Depends(current_user)) -> User:
        effective = get_effective_permissions(user)

        if Permission.FULL_ADMIN_PANEL_ACCESS in effective:
            return user

        if required not in effective:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "You do not have the required permissions for this action.",
            )

        return user

    return dependency
