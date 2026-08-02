"""Read-side capability projection.

Stamps a ``permissions`` map on resource DTOs from the same decision the write guards
enforce, so the client can hide controls the user would be 403'd on.

These maps are affordance hints only, never an authz input: every mutating route keeps
its own guard as the security boundary. Fail-closed — a key absent from the map reads
as ``False`` on the client.
"""

# Declared vocabulary for the cc_pair map; the coverage test fails if the keys stamped
# below drift from this set.
CC_PAIR_ACTIONS: frozenset[str] = frozenset({"edit", "delete", "publish"})


def cc_pair_permissions(
    *, is_editable: bool, is_connectors_admin: bool
) -> dict[str, bool]:
    """``is_editable`` is the managed-scope editable decision the write guard enforces
    (a scoped manager may edit a managed private connector; it also gates the
    manage-access control, so there is no separate key). ``delete`` and ``publish``
    (make org-wide PUBLIC) are global-only: a manager can edit a managed connector but
    never delete it or make it public."""
    return {
        "edit": is_editable,
        "delete": is_connectors_admin,
        "publish": is_connectors_admin,
    }


PERSONA_ACTIONS: frozenset[str] = frozenset(
    {"edit", "share", "view_stats", "delete", "publish", "feature", "list", "reorder"}
)


def persona_permissions(
    *,
    can_edit: bool,
    can_share: bool,
    can_view_stats: bool,
    can_delete: bool,
    is_manage_agents_admin: bool,
    is_full_admin: bool,
) -> dict[str, bool]:
    """Agent (persona) affordance map. ``edit`` is the editable-AND-managed-scope decision
    the update guard enforces; ``share`` is the broader editable decision the share guard
    enforces (get_editable alone, no scope AND) — an EDITOR-shared manager outside the
    agent's groups may share but not update, so share is not edit's gate. ``view_stats`` is
    owner-or-full-admin. ``delete``/``publish`` are owner-or-admin (the handler's own
    ownership check, not the route token). ``feature``/``list`` need global MANAGE_AGENTS
    and ``reorder`` needs full admin — so a scoped manager may edit a managed agent but
    not delete, publish, feature, list, or reorder it."""
    return {
        "edit": can_edit,
        "share": can_share,
        "view_stats": can_view_stats,
        "delete": can_delete,
        "publish": can_delete,
        "feature": is_manage_agents_admin,
        "list": is_manage_agents_admin,
        "reorder": is_full_admin,
    }


DOCUMENT_SET_ACTIONS: frozenset[str] = frozenset(
    {"edit", "manage_access", "delete", "publish"}
)


def document_set_permissions(
    *, is_editable: bool, is_document_sets_admin: bool
) -> dict[str, bool]:
    """Document set affordance map. ``edit`` and ``manage_access`` are the managed-scope
    editable decision the write guard enforces (a doc set has no editor-share arm, so
    editable membership is that decision). ``delete`` and ``publish`` (make org-wide
    public) are global MANAGE_DOCUMENT_SETS only."""
    return {
        "edit": is_editable,
        "manage_access": is_editable,
        "delete": is_document_sets_admin,
        "publish": is_document_sets_admin,
    }


TOOL_ACTIONS: frozenset[str] = frozenset({"edit", "delete", "toggle", "authenticate"})


def tool_permissions(*, can_manage: bool) -> dict[str, bool]:
    """Custom action (OpenAPI tool) affordance map. Every action — edit, delete, toggle, and
    authenticate (its OAuth config) — is owner-or-admin (``can_manage``): the creator fully
    controls the action they made and an admin controls any, while a scoped manager may view
    and create actions but not edit ones they didn't create."""
    return {
        "edit": can_manage,
        "delete": can_manage,
        "toggle": can_manage,
        "authenticate": can_manage,
    }


MCP_SERVER_ACTIONS: frozenset[str] = frozenset(
    {"edit", "delete", "authenticate", "manage_status"}
)


def mcp_server_permissions(*, can_manage: bool) -> dict[str, bool]:
    """MCP server affordance map. Every action — edit, delete, authenticate (connect), and
    manage_status (disconnect/refresh) — is owner-or-admin (``can_manage``): the owner fully
    controls their server and an admin controls any, while a scoped manager may view servers
    connected to their groups and create their own but not manage others'."""
    return {
        "edit": can_manage,
        "delete": can_manage,
        "authenticate": can_manage,
        "manage_status": can_manage,
    }


CUSTOM_SKILL_ACTIONS: frozenset[str] = frozenset(
    {"edit", "manage_access", "delete", "publish"}
)


def custom_skill_permissions(
    *, can_edit: bool, is_full_admin: bool, is_skills_admin: bool
) -> dict[str, bool]:
    """Custom skill affordance map. ``edit`` (replace bundle, enable/disable) and
    ``manage_access`` (group grants) are the managed-scope editable decision the write
    guard enforces. ``delete`` is FULL_ADMIN only (its route requires
    FULL_ADMIN_PANEL_ACCESS, no ``allow_scope``); ``publish`` (make org-wide public)
    needs global MANAGE_SKILLS — a scoped manager fails the guard's non-public check when
    flipping a skill public."""
    return {
        "edit": can_edit,
        "manage_access": can_edit,
        "delete": is_full_admin,
        "publish": is_skills_admin,
    }


USER_GROUP_ACTIONS: frozenset[str] = frozenset(
    {"manage", "delete", "edit_permissions", "edit_token_limits"}
)


def user_group_permissions(
    *, can_manage: bool, is_user_groups_admin: bool, is_full_admin: bool
) -> dict[str, bool]:
    """User group affordance map. ``manage`` (rename, membership, assign agents, set
    manager) and ``edit_token_limits`` are the per-group ``manages_group`` decision — group
    in the manager's managed set, or global MANAGE_USER_GROUPS. A scoped manager gets full
    token-limit CRUD for groups they manage: every token route (read/create/update/delete)
    now admits scope. ``delete`` needs global MANAGE_USER_GROUPS (its route has no
    ``allow_scope``). ``edit_permissions`` is FULL_ADMIN (the permission-toggle route)."""
    return {
        "manage": can_manage,
        "delete": is_user_groups_admin,
        "edit_permissions": is_full_admin,
        "edit_token_limits": can_manage,
    }
