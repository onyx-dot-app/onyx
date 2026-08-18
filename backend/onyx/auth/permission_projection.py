"""Read-side capability projection.

Stamps a ``permissions`` map on resource DTOs from the same decision the write guards
enforce, so the client can hide controls the user would be 403'd on.

These maps are affordance hints only, never an authz input: every mutating route keeps
its own guard as the security boundary. Fail-closed — a key absent from the map reads
as ``False`` on the client.
"""

from typing import TypedDict, cast

# Each resource's affordance keys are a TypedDict, so a typo or a missing key in the builder
# below is a type error rather than a silent False on the wire. The ``*_ACTIONS`` vocabulary is
# derived from the TypedDict (one source of truth), and the builders widen to the generic
# ``dict[str, bool]`` the DTO fields carry.


class CCPairPermissions(TypedDict):
    edit: bool
    delete: bool
    publish: bool


CC_PAIR_ACTIONS: frozenset[str] = frozenset(CCPairPermissions.__annotations__)


def cc_pair_permissions(
    *, is_editable: bool, is_connectors_admin: bool, owns_groupless: bool = False
) -> dict[str, bool]:
    """``is_editable`` is the managed-scope editable decision the write guard enforces
    (a scoped manager may edit a managed private connector; it also gates the
    manage-access control, so there is no separate key). ``publish`` (make org-wide
    PUBLIC) is global-only. So is ``delete``, except for a private groupless connector
    its creator made — mirrors the GATE 2 carve-out in create_deletion_attempt_for_connector_id."""
    result: CCPairPermissions = {
        "edit": is_editable,
        "delete": is_connectors_admin or owns_groupless,
        "publish": is_connectors_admin,
    }
    return cast(dict[str, bool], result)


class PersonaPermissions(TypedDict):
    edit: bool
    share: bool
    view_stats: bool
    delete: bool
    publish: bool
    feature: bool
    list: bool
    reorder: bool


PERSONA_ACTIONS: frozenset[str] = frozenset(PersonaPermissions.__annotations__)


def persona_permissions(
    *,
    can_edit: bool,
    can_share: bool,
    can_view_stats: bool,
    can_delete: bool,
    holds_add_agents: bool,
    is_manage_agents_admin: bool,
    is_full_admin: bool,
) -> dict[str, bool]:
    """Agent (persona) affordance map. ``edit``/``share`` gate on editable alone (their routes are
    BASIC_ACCESS) — an editor-shared user without ADD_AGENTS may still edit and manage sharing.
    ``edit`` is the editable-AND-managed-scope decision the update guard enforces; ``share`` is the
    broader editable decision the share guard enforces (get_editable, no scope AND). ``publish``
    (make org-wide public, via the share route's is_owner_or_admin gate) is owner-or-admin — no
    ADD_AGENTS. ``delete`` ANDs ``holds_add_agents``: its route gates on ADD_AGENTS at GATE 1
    (allow_scope), so an owner lacking it is 403'd there. ``view_stats`` needs
    READ_AGENT_ANALYTICS plus ownership — a global MANAGE_AGENTS holder implies both.
    ``feature``/``list`` need global MANAGE_AGENTS (which implies ADD_AGENTS) and ``reorder`` full
    admin."""
    result: PersonaPermissions = {
        "edit": can_edit,
        "share": can_share,
        "view_stats": can_view_stats,
        "delete": can_delete and holds_add_agents,
        "publish": can_delete,
        "feature": is_manage_agents_admin,
        "list": is_manage_agents_admin,
        "reorder": is_full_admin,
    }
    return cast(dict[str, bool], result)


class DocumentSetPermissions(TypedDict):
    edit: bool
    manage_access: bool
    delete: bool
    publish: bool


DOCUMENT_SET_ACTIONS: frozenset[str] = frozenset(DocumentSetPermissions.__annotations__)


def document_set_permissions(
    *, is_editable: bool, is_document_sets_admin: bool, owns_groupless: bool = False
) -> dict[str, bool]:
    """Document set affordance map. ``edit`` and ``manage_access`` are the managed-scope
    editable decision the write guard enforces (a doc set has no editor-share arm, so
    editable membership is that decision). ``publish`` (make org-wide public) is global
    MANAGE_DOCUMENT_SETS only. So is ``delete``, except for a private groupless set its
    creator made — mirrors the GATE 2 carve-out in delete_document_set."""
    result: DocumentSetPermissions = {
        "edit": is_editable,
        "manage_access": is_editable,
        "delete": is_document_sets_admin or owns_groupless,
        "publish": is_document_sets_admin,
    }
    return cast(dict[str, bool], result)


class ToolPermissions(TypedDict):
    edit: bool
    delete: bool
    toggle: bool
    authenticate: bool


TOOL_ACTIONS: frozenset[str] = frozenset(ToolPermissions.__annotations__)


def tool_permissions(*, can_manage: bool) -> dict[str, bool]:
    """Custom action (OpenAPI tool) affordance map. Every action — edit, delete, toggle, and
    authenticate (its OAuth config) — is owner-or-admin (``can_manage``): the creator fully
    controls the action they made and an admin controls any, while a scoped manager may view
    and create actions but not edit ones they didn't create."""
    result: ToolPermissions = {
        "edit": can_manage,
        "delete": can_manage,
        "toggle": can_manage,
        "authenticate": can_manage,
    }
    return cast(dict[str, bool], result)


class MCPServerPermissions(TypedDict):
    edit: bool
    delete: bool
    authenticate: bool
    manage_status: bool


MCP_SERVER_ACTIONS: frozenset[str] = frozenset(MCPServerPermissions.__annotations__)


def mcp_server_permissions(*, can_manage: bool) -> dict[str, bool]:
    """MCP server affordance map. Every action — edit, delete, authenticate (connect), and
    manage_status (disconnect/refresh) — is owner-or-admin (``can_manage``): the owner fully
    controls their server and an admin controls any, while a scoped manager may view servers
    connected to their groups and create their own but not manage others'."""
    result: MCPServerPermissions = {
        "edit": can_manage,
        "delete": can_manage,
        "authenticate": can_manage,
        "manage_status": can_manage,
    }
    return cast(dict[str, bool], result)


class CustomSkillPermissions(TypedDict):
    edit: bool
    manage_access: bool
    delete: bool
    publish: bool


CUSTOM_SKILL_ACTIONS: frozenset[str] = frozenset(CustomSkillPermissions.__annotations__)


def custom_skill_permissions(
    *, can_edit: bool, is_full_admin: bool, is_skills_admin: bool
) -> dict[str, bool]:
    """Custom skill affordance map. ``edit`` (replace bundle, enable/disable) and
    ``manage_access`` (group grants) are the managed-scope editable decision the write
    guard enforces. ``delete`` is FULL_ADMIN only (its route requires
    FULL_ADMIN_PANEL_ACCESS, no ``allow_scope``); ``publish`` (make org-wide public)
    needs global MANAGE_SKILLS — a scoped manager fails the guard's non-public check when
    flipping a skill public."""
    result: CustomSkillPermissions = {
        "edit": can_edit,
        "manage_access": can_edit,
        "delete": is_full_admin,
        "publish": is_skills_admin,
    }
    return cast(dict[str, bool], result)


class UserGroupPermissions(TypedDict):
    manage: bool
    delete: bool
    edit_permissions: bool
    edit_token_limits: bool


USER_GROUP_ACTIONS: frozenset[str] = frozenset(UserGroupPermissions.__annotations__)


def user_group_permissions(
    *, can_manage: bool, is_user_groups_admin: bool, is_full_admin: bool
) -> dict[str, bool]:
    """User group affordance map. ``manage`` (rename, membership, assign agents, set
    manager) and ``edit_token_limits`` are the per-group ``manages_group`` decision — group
    in the manager's managed set, or global MANAGE_USER_GROUPS. A scoped manager gets full
    token-limit CRUD for groups they manage: every token route (read/create/update/delete)
    now admits scope. ``delete`` needs global MANAGE_USER_GROUPS (its route has no
    ``allow_scope``). ``edit_permissions`` is FULL_ADMIN (the permission-toggle route)."""
    result: UserGroupPermissions = {
        "manage": can_manage,
        "delete": is_user_groups_admin,
        "edit_permissions": is_full_admin,
        "edit_token_limits": can_manage,
    }
    return cast(dict[str, bool], result)
