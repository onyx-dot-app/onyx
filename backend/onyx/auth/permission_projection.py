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
