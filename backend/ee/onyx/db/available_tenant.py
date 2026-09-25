from sqlalchemy.orm import Session

from onyx.db.models import AvailableTenant


def take_available_tenant(
    db_session: Session, at_revision: str | None
) -> tuple[str, str] | None:
    """Remove the oldest pool tenant and return its (tenant_id, alembic_version).

    ``at_revision`` restricts the choice to tenants migrated to that revision.
    Row-level locking with SKIP LOCKED keeps concurrent callers from taking the
    same tenant without making them wait on each other. Commits on success and
    leaves the transaction rolled back when the pool has nothing to offer.
    """
    query = db_session.query(AvailableTenant)
    if at_revision is not None:
        query = query.filter(AvailableTenant.alembic_version == at_revision)
    available_tenant = (
        query.order_by(AvailableTenant.date_created)
        .with_for_update(skip_locked=True)
        .first()
    )
    if available_tenant is None:
        db_session.rollback()
        return None

    taken = (available_tenant.tenant_id, available_tenant.alembic_version)
    db_session.delete(available_tenant)
    db_session.commit()
    return taken
