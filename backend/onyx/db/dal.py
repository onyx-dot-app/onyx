"""Base Data Access Layer (DAL) for database operations.

The DAL pattern groups related database operations into cohesive classes
with explicit session management. It supports two usage modes:

  1. **External session** (FastAPI endpoints) — the caller provides a session
     whose lifecycle is managed by FastAPI's dependency injection.

  2. **Self-managed session** (Celery tasks, scripts) — the DAL creates its
     own session via the tenant-aware session factory.

Subclasses add domain-specific query methods while inheriting session
management. See ``ee.onyx.db.scim.ScimDAL`` for a concrete example.

Example (FastAPI)::

    def get_scim_dal(db_session: Session = Depends(get_session)) -> ScimDAL:
        return ScimDAL(db_session)

    @router.get("/users")
    def list_users(dal: ScimDAL = Depends(get_scim_dal)) -> ...:
        return dal.list_user_mappings(...)

Example (Celery)::

    with ScimDAL.from_tenant("tenant_abc") as dal:
        dal.create_user_mapping(...)
        dal.commit()
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_tenant


class DAL:
    """Base Data Access Layer.

    Holds a SQLAlchemy session and provides transaction control helpers.
    Subclasses add domain-specific query methods.
    """

    def __init__(self, db_session: Session) -> None:
        self._session = db_session

    @property
    def session(self) -> Session:
        """Direct access to the underlying session for advanced use cases."""
        return self._session

    def commit(self) -> None:
        self._session.commit()

    def flush(self) -> None:
        self._session.flush()

    def rollback(self) -> None:
        self._session.rollback()

    @classmethod
    @contextmanager
    def from_tenant(cls, tenant_id: str) -> Generator["DAL", None, None]:
        """Create a DAL with a self-managed session for the given tenant.

        The session is automatically closed when the context manager exits.
        The caller must explicitly call ``commit()`` to persist changes.
        """
        with get_session_with_tenant(tenant_id=tenant_id) as session:
            yield cls(session)
