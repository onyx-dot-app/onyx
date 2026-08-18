"""
Scoped-manager authorization primitives.

Separate from the pure ``permissions.py``: the policy for a manager's live group
scope — the bundle guard and the write-side gate. DB access itself lives in
``onyx/db/scoped_permissions.py``; this layer only consumes that interface.
"""

from collections.abc import Collection

from sqlalchemy.orm import Session

from onyx.auth.permissions import (
    SCOPED_MANAGER_PERMISSIONS_EXPANDED,
    has_global_permission,
    has_permission,
)
from onyx.db.enums import Permission, PermissionAuthority
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
    user manages (scope introspection).

    Gate on the *expanded* bundle to match has_permission: an implied read a
    manager resolves SCOPED for must resolve a scope here, not an empty set."""
    if (
        permission is not None
        and permission.value not in SCOPED_MANAGER_PERMISSIONS_EXPANDED
    ):
        return set()
    return fetch_managed_group_ids(user, db_session)


def within_scope(
    user: User,
    db_session: Session,
    *,
    permission: Permission,
    current_group_ids: Collection[int],
    requested_group_ids: Collection[int],
    is_non_public: bool,
    managed_group_ids: set[int] | None = None,
) -> bool:
    """Pure GATE-2 (write) decision — no raise. GLOBAL holders always pass. A SCOPED
    manager passes only for a non-public resource whose every group (current ∪
    requested) is one they manage, landing in >=1 group. Fail-closed: NONE,
    out-of-scope, or empty managed scope is ``False``.

    ``managed_group_ids`` lets a caller pass a preloaded managed set so per-row
    stamping issues no DB query; ``None`` re-queries."""
    authority = has_permission(user, permission)
    if authority is PermissionAuthority.GLOBAL:
        return True
    if authority is PermissionAuthority.SCOPED:
        managed = (
            managed_group_ids
            if managed_group_ids is not None
            else get_scoped_groups(user, db_session, permission)
        )
        final = set(current_group_ids) | set(requested_group_ids)
        return bool(managed and final and final.issubset(managed) and is_non_public)
    return False


def assert_within_scope(
    user: User,
    db_session: Session,
    *,
    permission: Permission,
    current_group_ids: Collection[int],
    requested_group_ids: Collection[int],
    is_non_public: bool,
) -> None:
    """GATE 2 (write) — the authorization of record; raises 403 when out of scope.

    ``is_non_public`` is the caller's non-public predicate (PUBLIC excluded; for a
    cc_pair that admits PRIVATE or SYNC). On update, AND the current and requested
    states so a currently-PUBLIC resource can't be converted into managed scope.

    Call before any try/except in the endpoint: it raises a 403 OnyxError that a
    surrounding broad except would otherwise re-wrap as a 500. On create, pass
    ``current_group_ids=[]``; on update, pass the groups re-read from the DB — never
    the client's — so a reassignment can't escape scope."""
    if not within_scope(
        user,
        db_session,
        permission=permission,
        current_group_ids=current_group_ids,
        requested_group_ids=requested_group_ids,
        is_non_public=is_non_public,
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Group managers can only act on private resources "
            "within the groups they manage.",
        )


def manages_group(
    user: User,
    db_session: Session,
    *,
    group_id: int,
    managed_group_ids: set[int] | None = None,
) -> bool:
    """Pure GATE-2 decision for an action scoped to a single user group — no raise. A
    GLOBAL ``MANAGE_USER_GROUPS`` holder always passes; a scoped manager passes only
    for a group they manage. Fail-closed: empty managed scope is ``False``.
    ``managed_group_ids`` lets a caller pass a preloaded set so stamping issues no DB
    query."""
    if has_global_permission(user, Permission.MANAGE_USER_GROUPS):
        return True
    managed = (
        managed_group_ids
        if managed_group_ids is not None
        else get_scoped_groups(user, db_session, Permission.MANAGE_USER_GROUPS)
    )
    return group_id in managed


def assert_manages_group(user: User, db_session: Session, *, group_id: int) -> None:
    """GATE 2 for an action scoped to a single user group (membership edits, manager
    assignment): a GLOBAL ``MANAGE_USER_GROUPS`` holder bypasses; a scoped manager
    passes only for a group they manage. NONE, or out-of-scope, rejects."""
    if not manages_group(user, db_session, group_id=group_id):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Group managers can only act within the groups they manage.",
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
