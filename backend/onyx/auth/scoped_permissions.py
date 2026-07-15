"""
Scoped-manager authorization primitives.

Separate from the pure ``permissions.py``: these query the DB to resolve a
manager's live group scope. Inert until PR3+ wires endpoints/filters to them.
"""

from collections.abc import Collection

from sqlalchemy import and_
from sqlalchemy import ColumnElement
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_permission
from onyx.auth.permissions import SCOPED_MANAGER_PERMISSIONS
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


def scoped_group_ids_subquery(user: User) -> Select:
    """Subquery of the groups ``user`` manages; embed in a resource filter to
    keep the scope predicate in SQL (no extra round-trip)."""
    return select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user.id,
        User__UserGroup.is_manager.is_(True),
    )


def get_scoped_groups(
    user: User, db_session: Session, permission: Permission | None = None
) -> set[int]:
    """Imperative form for the write-side gate. Empty when ``permission`` is
    given but not scopable, so a non-bundle token never resolves a scope."""
    if permission is not None and permission not in SCOPED_MANAGER_PERMISSIONS:
        return set()
    return set(db_session.scalars(scoped_group_ids_subquery(user)).all())


def assert_within_scope(
    user: User,
    db_session: Session,
    *,
    permission: Permission,
    current_group_ids: Collection[int],
    requested_group_ids: Collection[int],
    is_private: bool,
) -> None:
    """GATE 2 (write) — the authorization of record. GLOBAL holders are governed
    by base-system rules. A SCOPED manager may only touch a private resource whose
    every group (current ∪ requested) is one they manage, landing in ≥1 group.
    NONE, or out-of-scope, rejects. Fail-closed: empty scope rejects."""
    authority = has_permission(user, permission)
    if authority is PermissionAuthority.GLOBAL:
        return
    if authority is PermissionAuthority.SCOPED:
        managed = get_scoped_groups(user, db_session, permission)
        final = set(current_group_ids) | set(requested_group_ids)
        if managed and final and final.issubset(managed) and is_private:
            return
    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "Group managers can only act on private resources "
        "within the groups they manage.",
    )


def assert_global(user: User, *, permission: Permission) -> None:
    """Admin-only gate (D6, rule A) for delete and other ops that share a bundle
    token with scoped create/update: the route admits a SCOPED manager, this
    rejects them — only GLOBAL authority passes."""
    if has_permission(user, permission) is not PermissionAuthority.GLOBAL:
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This action is restricted to administrators.",
        )


def within_managed_scope_clause(
    *,
    resource_id_col: InstrumentedAttribute[int],
    junction_resource_col: InstrumentedAttribute[int],
    junction_group_col: InstrumentedAttribute[int],
    is_private: ColumnElement[bool],
    managed_subq: Select,
) -> ColumnElement[bool]:
    """Read-side mirror of GATE 2: editable-by-manager iff every group is managed,
    in ≥1 group, and private. ``is_private`` is the caller's privateness predicate —
    resources encode it differently (``DocumentSet.is_public.is_(False)`` vs
    ``ConnectorCredentialPair.access_type == AccessType.PRIVATE``). ``managed_subq``
    yields no rows for a non-manager, so the clause fails closed."""
    belongs_to_managed = (
        select(junction_resource_col)
        .where(
            junction_resource_col == resource_id_col,
            junction_group_col.in_(managed_subq),
        )
        .exists()
    )
    belongs_to_unmanaged = (
        select(junction_resource_col)
        .where(
            junction_resource_col == resource_id_col,
            ~junction_group_col.in_(managed_subq),
        )
        .exists()
    )
    return and_(is_private, belongs_to_managed, ~belongs_to_unmanaged)
