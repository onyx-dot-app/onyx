"""Direct reads of permission state, for subjects a test can't authenticate as —
``/me/permissions`` only exposes the caller's own, and SCIM-provisioned users have
no password.

Prefer ``/me/permissions`` plus a real gated route when the subject can log in:
that proves the whole chain, a column read only proves the projection.
"""

from uuid import UUID

from sqlalchemy import select

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User, User__UserGroup


def effective_permissions(user_id: str | UUID) -> set[str]:
    with get_session_with_current_tenant() as db_session:
        value = db_session.scalar(
            select(User.effective_permissions).where(
                User.id == user_id  # ty: ignore[invalid-argument-type]
            )
        )
        return set(value or [])


def is_group_manager(user_id: str | UUID) -> bool:
    """The cached rollup the route gate reads."""
    with get_session_with_current_tenant() as db_session:
        value = db_session.scalar(
            select(User.is_group_manager).where(
                User.id == user_id  # ty: ignore[invalid-argument-type]
            )
        )
        assert value is not None, f"no user row for {user_id}"
        return value


def managed_group_ids(user_id: str | UUID) -> set[int]:
    """Edges carrying is_manager — the source the rollup derives from. Assert on
    both; they can disagree."""
    with get_session_with_current_tenant() as db_session:
        return set(
            db_session.scalars(
                select(User__UserGroup.user_group_id).where(
                    User__UserGroup.user_id == user_id,
                    User__UserGroup.is_manager.is_(True),
                )
            )
        )
