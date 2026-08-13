"""DB-layer scope resolution for group-manager scoped permissions.

Raw SQLAlchemy primitives — the managed-group subquery/read plus the read-side
scope clause. The authorization policy that consumes these (bundle guard + the
GATE 2 write gate) lives in ``onyx/auth/scoped_permissions.py``.
"""

from typing import TypeVar

from sqlalchemy import ColumnElement, Select, and_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.db.models import User, User__UserGroup, UserGroup

# Resource PK type — int for connectors/doc-sets, UUID for skills. The clause is
# key-type agnostic; the TypeVar just ties the resource + junction cols together.
_ResourceId = TypeVar("_ResourceId")


def scoped_group_ids_subquery(user: User) -> Select:
    """Subquery of the groups ``user`` manages; embed in a resource filter to
    keep the scope predicate in SQL (no extra round-trip).

    Default groups (Basic/Admin) are excluded: "Basic" holds the whole org, so a
    manager edge on it — e.g. the GLOBAL_CURATOR migration backfill — would confer
    org-wide scope. Managing a default group never grants scope."""
    return (
        select(User__UserGroup.user_group_id)
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .where(
            User__UserGroup.user_id == user.id,
            User__UserGroup.is_manager.is_(True),
            UserGroup.is_default.is_(False),
        )
    )


def fetch_managed_group_ids(user: User, db_session: Session) -> set[int]:
    """Execute ``scoped_group_ids_subquery`` — the ids of groups ``user`` manages."""
    return set(db_session.scalars(scoped_group_ids_subquery(user)).all())


def within_managed_scope_clause(
    *,
    resource_id_col: InstrumentedAttribute[_ResourceId],
    junction_resource_col: InstrumentedAttribute[_ResourceId],
    junction_group_col: InstrumentedAttribute[int],
    non_public_clause: ColumnElement[bool],
    managed_subq: Select,
    junction_live_clause: ColumnElement[bool] | None = None,
) -> ColumnElement[bool]:
    """Read-side mirror of GATE 2: editable-by-manager iff every group is managed,
    in ≥1 group, and non-public. ``non_public_clause`` is the caller's non-public
    predicate — resources encode it differently (``DocumentSet.is_public.is_(False)``
    vs ``ConnectorCredentialPair.access_type != AccessType.PUBLIC``). ``managed_subq``
    yields no rows for a non-manager, so the clause fails closed.

    ``junction_live_clause`` narrows both EXISTS to live junction rows. Pass it for a
    junction that keeps history — a group edit marks every cc_pair row
    ``is_current=False`` until the sync cleans up, and counting those would both admit a
    detached pair and hide an attached one. Omit it where rows have no history."""
    junction_filters = () if junction_live_clause is None else (junction_live_clause,)
    belongs_to_managed = (
        select(junction_resource_col)
        .where(
            junction_resource_col == resource_id_col,
            junction_group_col.in_(managed_subq),
            *junction_filters,
        )
        .exists()
    )
    belongs_to_unmanaged = (
        select(junction_resource_col)
        .where(
            junction_resource_col == resource_id_col,
            ~junction_group_col.in_(managed_subq),
            *junction_filters,
        )
        .exists()
    )
    return and_(non_public_clause, belongs_to_managed, ~belongs_to_unmanaged)
