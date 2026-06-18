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
from fastapi import Request

from onyx.auth.users import current_chat_accessible_user
from onyx.auth.users import current_user
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.permissions import parse_permission_values
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

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
    # basic grants the search/chat surfaces; admin grants read:admin (and the
    # rest) via the FULL_ADMIN_PANEL_ACCESS short-circuit in
    # resolve_effective_permissions.
    Permission.BASIC_ACCESS.value: {
        Permission.READ_SEARCH.value,
        Permission.READ_CHAT.value,
        Permission.WRITE_CHAT.value,
    },
    Permission.WRITE_CHAT.value: {Permission.READ_CHAT.value},
}

# Permissions that cannot be toggled via the group-permission API.
# BASIC_ACCESS is always granted, FULL_ADMIN_PANEL_ACCESS is too broad,
# and implied permissions (READ_* and the API-surface scopes) are never
# stored directly.
NON_TOGGLEABLE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.BASIC_ACCESS,
        Permission.FULL_ADMIN_PANEL_ACCESS,
    }
    | Permission.IMPLIED
)


def resolve_effective_permissions(granted: set[str]) -> set[str]:
    """Expand granted permissions with their implied permissions.

    If "admin" is present, returns all permissions.
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
    granted = set(parse_permission_values(user.effective_permissions))
    if Permission.FULL_ADMIN_PANEL_ACCESS in granted:
        return set(Permission)
    expanded = resolve_effective_permissions({p.value for p in granted})
    return {Permission(p) for p in expanded}


def require_permission(
    required: Permission,
    *,
    allow_anonymous: bool = False,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """FastAPI dependency factory: require ``required`` of the caller, capped by the
    authenticating token's scopes (unrestricted PAT / session / API key = no cap).
    allow_anonymous admits the anonymous user where the tenant permits it (the
    anonymous-capable chat surface)."""
    base_user = current_chat_accessible_user if allow_anonymous else current_user

    async def dependency(request: Request, user: User = Depends(base_user)) -> User:
        token_scopes: list[Permission] | None = getattr(
            request.state, "token_scopes", None
        )
        permitted_by_user = required in get_effective_permissions(user)
        permitted_by_token = token_scopes is None or required.value in (
            resolve_effective_permissions({s.value for s in token_scopes})
        )
        if not (permitted_by_user and permitted_by_token):
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "You do not have the required permissions for this action.",
            )
        return user

    dependency._is_require_permission = True  # ty: ignore[unresolved-attribute]
    return dependency
