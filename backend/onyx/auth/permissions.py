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
from pydantic import BaseModel
from pydantic import field_validator

from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import global_version

logger = setup_logger()

ALL_PERMISSIONS: frozenset[str] = frozenset(p.value for p in Permission)

# Implication map: granted permission -> set of permissions it implies.
IMPLIED_PERMISSIONS: dict[str, set[str]] = {
    Permission.ADD_AGENTS.value: {Permission.READ_AGENTS.value},
    Permission.MANAGE_AGENTS.value: {
        Permission.ADD_AGENTS.value,
        Permission.READ_AGENTS.value,
        Permission.READ_DOCUMENT_SETS.value,
    },
    Permission.MANAGE_DOCUMENT_SETS.value: {
        Permission.READ_DOCUMENT_SETS.value,
        Permission.READ_CONNECTORS.value,
        Permission.READ_USER_GROUPS.value,
    },
    Permission.MANAGE_CONNECTORS.value: {
        Permission.READ_CONNECTORS.value,
    },
    Permission.MANAGE_USER_GROUPS.value: {
        Permission.READ_CONNECTORS.value,
        Permission.READ_DOCUMENT_SETS.value,
        Permission.READ_AGENTS.value,
        Permission.READ_USERS.value,
        Permission.READ_USER_GROUPS.value,
    },
    Permission.MANAGE_LLMS.value: {
        Permission.READ_USER_GROUPS.value,
        Permission.READ_AGENTS.value,
        Permission.READ_USERS.value,
    },
}

# Permissions that cannot be toggled via the group-permission API.
# BASIC_ACCESS is always granted, FULL_ADMIN_PANEL_ACCESS is too broad,
# and READ_* permissions are implied (never stored directly).
NON_TOGGLEABLE_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.BASIC_ACCESS,
        Permission.FULL_ADMIN_PANEL_ACCESS,
        Permission.READ_CONNECTORS,
        Permission.READ_DOCUMENT_SETS,
        Permission.READ_AGENTS,
        Permission.READ_USERS,
        Permission.READ_USER_GROUPS,
    }
)

# Permissions auto-granted to all users in Community Edition.
# In CE there is no group-permission UI, so these capabilities must be
# available without explicit grants.  In EE they are controlled normally
# via group permissions.
CE_UNGATED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.ADD_AGENTS,
    }
)


class PermissionRegistryEntry(BaseModel):
    """A UI-facing permission row served by GET /admin/permissions/registry.

    The field_validator ensures non-toggleable permissions (BASIC_ACCESS,
    FULL_ADMIN_PANEL_ACCESS, READ_*) can never appear in the registry.
    """

    id: str
    display_name: str
    description: str
    permissions: list[Permission]
    group: int

    @field_validator("permissions")
    @classmethod
    def must_be_toggleable(cls, v: list[Permission]) -> list[Permission]:
        for p in v:
            if p in NON_TOGGLEABLE_PERMISSIONS:
                raise ValueError(
                    f"Permission '{p.value}' is not toggleable and "
                    "cannot be included in the permission registry"
                )
        return v


# Registry of toggleable permissions exposed to the admin UI.
# Single source of truth for display names, descriptions, grouping,
# and which backend tokens each UI row controls.
# The frontend fetches this via GET /admin/permissions/registry
# and only adds icon mapping locally.
PERMISSION_REGISTRY: list[PermissionRegistryEntry] = [
    # Group 0 — System Configuration
    PermissionRegistryEntry(
        id="manage_llms",
        display_name="Manage LLMs",
        description="Add and update configurations for language models (LLMs).",
        permissions=[Permission.MANAGE_LLMS],
        group=0,
    ),
    PermissionRegistryEntry(
        id="manage_connectors_and_document_sets",
        display_name="Manage Connectors & Document Sets",
        description="Add and update connectors and document sets.",
        permissions=[
            Permission.MANAGE_CONNECTORS,
            Permission.MANAGE_DOCUMENT_SETS,
        ],
        group=0,
    ),
    PermissionRegistryEntry(
        id="manage_actions",
        display_name="Manage Actions",
        description="Add and update custom tools and MCP/OpenAPI actions.",
        permissions=[Permission.MANAGE_ACTIONS],
        group=0,
    ),
    # Group 1 — User & Access Management
    PermissionRegistryEntry(
        id="manage_groups",
        display_name="Manage Groups",
        description="Add and update user groups.",
        permissions=[Permission.MANAGE_USER_GROUPS],
        group=1,
    ),
    PermissionRegistryEntry(
        id="manage_service_accounts",
        display_name="Manage Service Accounts",
        description="Add and update service accounts and their API keys.",
        permissions=[Permission.MANAGE_SERVICE_ACCOUNT_API_KEYS],
        group=1,
    ),
    PermissionRegistryEntry(
        id="manage_bots",
        display_name="Manage Slack/Discord Bots",
        description="Add and update Onyx integrations with Slack or Discord.",
        permissions=[Permission.MANAGE_BOTS],
        group=1,
    ),
    # Group 2 — Agents
    PermissionRegistryEntry(
        id="create_agents",
        display_name="Create Agents",
        description="Create and edit the user's own agents.",
        permissions=[Permission.ADD_AGENTS],
        group=2,
    ),
    PermissionRegistryEntry(
        id="manage_agents",
        display_name="Manage Agents",
        description="View and update all public and shared agents in the organization.",
        permissions=[Permission.MANAGE_AGENTS],
        group=2,
    ),
    # Group 3 — Monitoring & Tokens
    PermissionRegistryEntry(
        id="view_agent_analytics",
        display_name="View Agent Analytics",
        description="View analytics for agents the group can manage.",
        permissions=[Permission.READ_AGENT_ANALYTICS],
        group=3,
    ),
    PermissionRegistryEntry(
        id="view_query_history",
        display_name="View Query History",
        description="View query history of everyone in the organization.",
        permissions=[Permission.READ_QUERY_HISTORY],
        group=3,
    ),
    PermissionRegistryEntry(
        id="create_user_access_token",
        display_name="Create User Access Token",
        description="Add and update the user's personal access tokens.",
        permissions=[Permission.CREATE_USER_API_KEYS],
        group=3,
    ),
]


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
    """Read granted permissions from the column and expand implied permissions.

    Admin-role users always receive all permissions regardless of the JSONB
    column, maintaining backward compatibility with role-based access control.
    """

    granted: set[Permission] = set()
    for p in user.effective_permissions:
        try:
            granted.add(Permission(p))
        except ValueError:
            logger.warning(f"Skipping unknown permission '{p}' for user {user.id}")
    if Permission.FULL_ADMIN_PANEL_ACCESS in granted:
        return set(Permission)

    if not global_version.is_ee_version():
        granted |= CE_UNGATED_PERMISSIONS

    expanded = resolve_effective_permissions({p.value for p in granted})
    return {Permission(p) for p in expanded}


def has_permission(user: User, permission: Permission) -> bool:
    """Check whether *user* holds *permission* (directly or via implication/admin override)."""
    return permission in get_effective_permissions(user)


def _get_current_user() -> Any:
    """Lazy import to break circular dependency between permissions and users modules."""
    from onyx.auth.users import current_user

    return current_user


def require_permission(
    required: Permission,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """FastAPI dependency factory for permission-based access control.

    Usage:
        @router.get("/endpoint")
        def endpoint(user: User = Depends(require_permission(Permission.MANAGE_CONNECTORS))):
            ...
    """

    async def dependency(
        user: User = Depends(_get_current_user()),
    ) -> User:
        effective = get_effective_permissions(user)

        if Permission.FULL_ADMIN_PANEL_ACCESS in effective:
            return user

        if required not in effective:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "You do not have the required permissions for this action.",
            )

        return user

    dependency._is_require_permission = True  # type: ignore[attr-defined]  # sentinel for auth_check detection
    return dependency
