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
from pydantic import BaseModel
from pydantic import field_validator

from onyx.db.enums import AccountType
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.db.models import User
from onyx.db.permissions import parse_permission_values
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
    Permission.MANAGE_SERVICE_ACCOUNT_API_KEYS.value: {
        Permission.READ_USER_GROUPS.value,
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

# Permissions auto-granted to all users in Community Edition.
# In CE there is no group-permission UI, so these capabilities must be
# available without explicit grants.  In EE they are controlled normally
# via group permissions.
CE_UNGATED_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.ADD_AGENTS,
    }
)

# Abilities a group manager may exercise, scoped to the groups they manage.
# Never persisted to permission_grant or merged into effective_permissions
# (which stays global-only); has_permission reads it to classify SCOPED
# authority, so it lives here, not in scoped_permissions.py (one-way import).
SCOPED_MANAGER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        Permission.MANAGE_CONNECTORS,
        Permission.MANAGE_DOCUMENT_SETS,
        Permission.MANAGE_AGENTS,
        Permission.ADD_AGENTS,
        Permission.MANAGE_USER_GROUPS,
        Permission.MANAGE_ACTIONS,  # scoped via its agents at GATE 2
        Permission.MANAGE_SKILLS,  # not yet enforced (no registry)
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

    # CE auto-grants capabilities (no permission UI exists), but never to the
    # anonymous user — it stays a chat-only surface.
    if (
        not global_version.is_ee_version()
        and user.account_type != AccountType.ANONYMOUS
    ):
        granted |= CE_UNGATED_PERMISSIONS

    expanded = resolve_effective_permissions({p.value for p in granted})
    return {Permission(p) for p in expanded}


def has_permission(user: User, permission: Permission) -> PermissionAuthority:
    """Classify *user*'s authority for *permission*: GLOBAL (holds it outright /
    admin), SCOPED (group manager — only within managed groups), or NONE.

    A scoped grant is group-qualified, so it cannot be a flat bool; callers act
    on the kind (GLOBAL → unrestricted, SCOPED → check resource scope at GATE 2).
    """
    if permission in get_effective_permissions(user):
        return PermissionAuthority.GLOBAL
    if permission in SCOPED_MANAGER_PERMISSIONS and user.is_group_manager:
        return PermissionAuthority.SCOPED
    return PermissionAuthority.NONE


def has_global_permission(user: User, permission: Permission) -> bool:
    """True iff *user* holds *permission* outright (global grant / admin) — the
    GLOBAL-only convenience over has_permission, for checks that must exclude
    scoped managers."""
    return has_permission(user, permission) is PermissionAuthority.GLOBAL


def require_permission(
    required: Permission,
    *,
    allow_anonymous: bool = False,
    allow_scope: bool = False,
) -> Callable[..., Coroutine[Any, Any, User]]:
    """FastAPI dependency factory: require ``required`` of the caller, capped by the
    authenticating token's scopes (unrestricted PAT / session / API key = no cap).
    allow_anonymous admits the anonymous user on the chat surface.

    allow_scope (GATE 1) also lets a SCOPED group manager *reach* the handler — reach
    only, never authorize. If you set it, the handler MUST scope the manager itself
    (GATE 2 assert_within_scope for writes, within_managed_scope_clause for reads) or
    they get every resource. Never on delete / set_group_permissions routes."""
    # Lazy import to break the circular dependency between permissions and users
    # (users.py imports has_permission from this module at top level).
    from onyx.auth.users import current_chat_accessible_user
    from onyx.auth.users import current_user

    base_user = current_chat_accessible_user if allow_anonymous else current_user

    async def dependency(request: Request, user: User = Depends(base_user)) -> User:
        token_scopes: list[Permission] | None = getattr(
            request.state, "token_scopes", None
        )
        authority = has_permission(user, required)
        # allow_scope: GATE 1 lets a SCOPED manager reach the route; default GLOBAL-only.
        if allow_scope:
            permitted_by_user = authority is not PermissionAuthority.NONE
        else:
            permitted_by_user = authority is PermissionAuthority.GLOBAL
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
