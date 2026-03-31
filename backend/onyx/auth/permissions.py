"""
Permission resolution for group-based authorization.

Granted permissions are stored as a JSONB column on the User table and
loaded for free with every auth query. Implied permissions are expanded
at read time — only directly granted permissions are persisted.
"""

from collections.abc import Callable
from collections.abc import Coroutine
from typing import Any

from fastapi import Depends

from onyx.auth.users import current_user
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger

logger = setup_logger()

ALL_PERMISSIONS: frozenset[str] = frozenset(p.value for p in Permission)

# Implication map: granted permission -> set of permissions it implies.
IMPLIED_PERMISSIONS: dict[str, set[str]] = {
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
            implied = IMPLIED_PERMISSIONS.get(perm)
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
