"""DB-layer scope resolution for group-manager scoped permissions.

Raw SQLAlchemy primitives — the managed-group subquery/read plus the read-side
scope clause. The authorization policy that consumes these (bundle guard + the
GATE 2 write gate) lives in ``onyx/auth/scoped_permissions.py``.
"""

from sqlalchemy import and_
from sqlalchemy import ColumnElement
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.models import User__UserGroup


def scoped_group_ids_subquery(user: User) -> Select:
    """Subquery of the groups ``user`` manages; embed in a resource filter to
    keep the scope predicate in SQL (no extra round-trip)."""
    return select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == user.id,
        User__UserGroup.is_manager.is_(True),
    )


def fetch_managed_group_ids(user: User, db_session: Session) -> set[int]:
    """Execute ``scoped_group_ids_subquery`` — the ids of groups ``user`` manages."""
    return set(db_session.scalars(scoped_group_ids_subquery(user)).all())


def within_managed_scope_clause(
    *,
    resource_id_col: InstrumentedAttribute[int],
    junction_resource_col: InstrumentedAttribute[int],
    junction_group_col: InstrumentedAttribute[int],
    non_public_clause: ColumnElement[bool],
    managed_subq: Select,
) -> ColumnElement[bool]:
    """Read-side mirror of GATE 2: editable-by-manager iff every group is managed,
    in ≥1 group, and non-public. ``non_public_clause`` is the caller's non-public
    predicate — resources encode it differently (``DocumentSet.is_public.is_(False)``
    vs ``ConnectorCredentialPair.access_type != AccessType.PUBLIC``). ``managed_subq``
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
    return and_(non_public_clause, belongs_to_managed, ~belongs_to_unmanaged)
