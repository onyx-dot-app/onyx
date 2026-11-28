"""Queries for tenant provisioning: the pre-provisioned tenant pool and the
anonymous user path, both in the shared `public` schema, and the search
settings reads that tenant setup makes inside a tenant schema."""

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import (
    AvailableTenant,
    IndexModelStatus,
    SearchSettings,
    TenantAnonymousUserPath,
)


def count_available_tenants(db_session: Session) -> int:
    return db_session.query(AvailableTenant).count()


def get_available_tenants(db_session: Session) -> list[AvailableTenant]:
    return db_session.query(AvailableTenant).all()


def get_available_tenant_by_id(
    db_session: Session, tenant_id: str
) -> AvailableTenant | None:
    return (
        db_session.query(AvailableTenant)
        .filter(AvailableTenant.tenant_id == tenant_id)
        .first()
    )


def lock_oldest_available_tenant(db_session: Session) -> AvailableTenant | None:
    """The oldest pool tenant under a row lock, until the transaction ends.
    Skips locked rows, so concurrent callers each get a different tenant."""
    return (
        db_session.query(AvailableTenant)
        .order_by(AvailableTenant.date_created)
        .with_for_update(skip_locked=True)
        .first()
    )


def create_available_tenant__no_commit(
    db_session: Session,
    tenant_id: str,
    alembic_version: str,
    date_created: datetime.datetime,
    shard_name: str,
) -> AvailableTenant:
    new_tenant = AvailableTenant(
        tenant_id=tenant_id,
        alembic_version=alembic_version,
        date_created=date_created,
        shard_name=shard_name,
    )
    db_session.add(new_tenant)
    return new_tenant


def delete_available_tenant__no_commit(
    db_session: Session, available_tenant: AvailableTenant
) -> None:
    db_session.delete(available_tenant)


def get_tenant_anonymous_user_path(db_session: Session, tenant_id: str) -> str | None:
    result = db_session.execute(
        select(TenantAnonymousUserPath).where(
            TenantAnonymousUserPath.tenant_id == tenant_id
        )
    )
    result_scalar = result.scalar_one_or_none()
    if result_scalar:
        return result_scalar.anonymous_user_path
    else:
        return None


def get_tenant_id_by_anonymous_user_path(
    db_session: Session, anonymous_user_path: str
) -> str | None:
    result = db_session.execute(
        select(TenantAnonymousUserPath).where(
            TenantAnonymousUserPath.anonymous_user_path == anonymous_user_path
        )
    )
    result_scalar = result.scalar_one_or_none()
    if result_scalar:
        return result_scalar.tenant_id
    else:
        return None


def upsert_tenant_anonymous_user_path__no_commit(
    db_session: Session, tenant_id: str, anonymous_user_path: str
) -> None:
    existing_entry = (
        db_session.query(TenantAnonymousUserPath).filter_by(tenant_id=tenant_id).first()
    )

    if existing_entry:
        existing_entry.anonymous_user_path = anonymous_user_path

    else:
        new_entry = TenantAnonymousUserPath(
            tenant_id=tenant_id, anonymous_user_path=anonymous_user_path
        )
        db_session.add(new_entry)


def get_latest_search_settings_by_status(
    db_session: Session, status: IndexModelStatus
) -> SearchSettings | None:
    """Unlike `get_current_search_settings`, returns None when no row has the
    status."""
    query = (
        select(SearchSettings)
        .where(SearchSettings.status == status)
        .order_by(SearchSettings.id.desc())
    )
    result = db_session.execute(query)
    return result.scalars().first()


def get_first_search_settings_by_status(
    db_session: Session, status: IndexModelStatus
) -> SearchSettings | None:
    """Unordered: when several rows have the status, which one comes back is
    up to Postgres."""
    return db_session.query(SearchSettings).filter_by(status=status).first()
