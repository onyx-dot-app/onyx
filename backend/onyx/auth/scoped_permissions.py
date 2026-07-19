"""
Scoped-manager authorization primitives.

Separate from the pure ``permissions.py``: the policy for a manager's live group
scope — the bundle guard and the write-side gate. DB access itself lives in
``onyx/db/scoped_permissions.py``; this layer only consumes that interface.
"""

from collections.abc import Collection

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_permission
from onyx.auth.permissions import SCOPED_MANAGER_PERMISSIONS
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.db.models import User
from onyx.db.scoped_permissions import fetch_managed_group_ids
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def get_scoped_groups(
    user: User, db_session: Session, permission: Permission | None = None
) -> set[int]:
    """Imperative form for the write-side gate. Empty when ``permission`` is
    given but not scopable, so a non-bundle token never resolves a scope. When
    ``permission`` is ``None``, skips the bundle check and returns all groups the
    user manages (scope introspection)."""
    if permission is not None and permission not in SCOPED_MANAGER_PERMISSIONS:
        return set()
    return fetch_managed_group_ids(user, db_session)


def agent_mediated_scope_allows(
    user: User,
    db_session: Session,
    *,
    group_ids: set[int],
    has_public_agent: bool,
) -> bool:
    """Shared GATE 2 tail for resources whose scope is derived from the agents that
    reference them (custom actions, MCP servers). A scoped manager is in scope iff
    no referencing agent is public, there is ≥1 group, and every group is one they
    manage. Callers resolve owner/admin bypasses first."""
    if has_public_agent or not group_ids:
        return False
    managed = get_scoped_groups(user, db_session, Permission.MANAGE_ACTIONS)
    return group_ids.issubset(managed)


def assert_within_scope(
    user: User,
    db_session: Session,
    *,
    permission: Permission,
    current_group_ids: Collection[int],
    requested_group_ids: Collection[int],
    is_non_public: bool,
) -> None:
    """GATE 2 (write) — the authorization of record. GLOBAL holders are governed
    by base-system rules. A SCOPED manager may only touch a non-public resource
    whose every group (current ∪ requested) is one they manage, landing in ≥1
    group. NONE, or out-of-scope, rejects. Fail-closed: empty scope rejects.

    ``is_non_public`` is the caller's non-public predicate (PUBLIC excluded; for a
    cc_pair that admits PRIVATE or SYNC). On update, AND the current and requested
    states so a currently-PUBLIC resource can't be converted into managed scope.

    Call before any try/except in the endpoint: it raises a 403 OnyxError that a
    surrounding broad except would otherwise re-wrap as a 500. On create, pass
    ``current_group_ids=[]`` (no existing groups); on update, pass the groups
    re-read from the DB — never the client's — so a reassignment can't escape scope."""
    authority = has_permission(user, permission)
    if authority is PermissionAuthority.GLOBAL:
        return
    if authority is PermissionAuthority.SCOPED:
        managed = get_scoped_groups(user, db_session, permission)
        final = set(current_group_ids) | set(requested_group_ids)
        if managed and final and final.issubset(managed) and is_non_public:
            return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "Group managers can only act on private resources "
        "within the groups they manage.",
    )


def assert_global(user: User, *, permission: Permission) -> None:
    """Admin-only gate for delete and other ops that share a bundle token with
    scoped create/update: the route admits a SCOPED manager, this rejects them —
    only GLOBAL authority passes."""
    if has_permission(user, permission) is not PermissionAuthority.GLOBAL:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This action is restricted to administrators.",
        )
