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
    can_view_stats: bool,
    can_delete: bool,
    is_manage_agents_admin: bool,
    is_full_admin: bool,
) -> dict[str, bool]:
    """Agent (persona) affordance map. ``edit``/``share`` are the scoped
    editable-and-managed-scope decision (share shares edit's gate). ``view_stats`` is
    owner-or-full-admin. ``delete``/``publish`` are owner-or-admin (the handler's own
    ownership check, not the route token). ``feature``/``list`` need global MANAGE_AGENTS
    and ``reorder`` needs full admin — so a scoped manager may edit a managed agent but
    not delete, publish, feature, list, or reorder it."""
    return {
        "edit": can_edit,
        "share": can_edit,
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
