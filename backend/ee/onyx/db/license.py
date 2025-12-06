"""Database and cache operations for the license table."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.server.license.models import LicenseMetadata
from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import LicenseSource
from onyx.db.models import License
from onyx.db.models import User
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.redis_pool import get_redis_replica_client
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

LICENSE_METADATA_KEY = "license:metadata"
LICENSE_CACHE_TTL_SECONDS = 86400  # 24 hours


# -----------------------------------------------------------------------------
# Database CRUD Operations
# -----------------------------------------------------------------------------


def get_license(db_session: Session) -> License | None:
    """
    Get the current license (singleton pattern - only one row).

    Args:
        db_session: Database session

    Returns:
        License object if exists, None otherwise
    """
    return db_session.execute(select(License)).scalars().first()


def upsert_license(db_session: Session, license_data: str) -> License:
    """
    Insert or update the license (singleton pattern).

    Args:
        db_session: Database session
        license_data: Base64-encoded signed license blob

    Returns:
        The created or updated License object
    """
    existing = get_license(db_session)

    if existing:
        existing.license_data = license_data
        db_session.commit()
        db_session.refresh(existing)
        logger.info("License updated")
        return existing

    new_license = License(license_data=license_data)
    db_session.add(new_license)
    db_session.commit()
    db_session.refresh(new_license)
    logger.info("License created")
    return new_license


def delete_license(db_session: Session) -> bool:
    """
    Delete the current license.

    Args:
        db_session: Database session

    Returns:
        True if deleted, False if no license existed
    """
    existing = get_license(db_session)
    if existing:
        db_session.delete(existing)
        db_session.commit()
        logger.info("License deleted")
        return True
    return False


# -----------------------------------------------------------------------------
# Seat Counting
# -----------------------------------------------------------------------------


def get_used_seats(tenant_id: str | None = None) -> int:
    """Get current seat usage."""
    if MULTI_TENANT:
        from ee.onyx.server.tenants.user_mapping import get_tenant_count

        return get_tenant_count(tenant_id or get_current_tenant_id())
    else:
        # Self-hosted: count all active users
        from onyx.db.engine.sql_engine import get_session_with_current_tenant

        with get_session_with_current_tenant() as db_session:
            result = db_session.execute(
                select(func.count()).select_from(User).where(User.is_active)  # type: ignore
            )
            return result.scalar() or 0


# -----------------------------------------------------------------------------
# Redis Cache Operations
# -----------------------------------------------------------------------------


def get_cached_license_metadata(tenant_id: str | None = None) -> LicenseMetadata | None:
    """
    Get license metadata from Redis cache.

    Args:
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        LicenseMetadata if cached, None otherwise
    """
    tenant = tenant_id or get_current_tenant_id()
    redis_client = get_redis_replica_client(tenant_id=tenant)

    cached = redis_client.get(LICENSE_METADATA_KEY)
    if cached:
        try:
            cached_str: str
            if isinstance(cached, bytes):
                cached_str = cached.decode("utf-8")
            else:
                cached_str = str(cached)
            return LicenseMetadata.model_validate_json(cached_str)
        except Exception as e:
            logger.warning(f"Failed to parse cached license metadata: {e}")
            return None
    return None


def invalidate_license_cache(tenant_id: str | None = None) -> None:
    """
    Invalidate the license cache.

    Args:
        tenant_id: Tenant ID (for multi-tenant deployments)
    """
    tenant = tenant_id or get_current_tenant_id()
    redis_client = get_redis_client(tenant_id=tenant)
    redis_client.delete(LICENSE_METADATA_KEY)
    logger.info("License cache invalidated")


def update_license_cache(
    payload: LicensePayload,
    source: LicenseSource | None = None,
    grace_period_end: datetime | None = None,
    tenant_id: str | None = None,
) -> LicenseMetadata:
    """
    Update the Redis cache with license metadata.

    Args:
        payload: Verified license payload
        source: How the license was obtained
        grace_period_end: Optional grace period end time
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        The cached LicenseMetadata
    """
    from ee.onyx.utils.license import get_license_status

    tenant = tenant_id or get_current_tenant_id()
    redis_client = get_redis_client(tenant_id=tenant)

    used_seats = get_used_seats(tenant)
    status = get_license_status(payload, grace_period_end)

    metadata = LicenseMetadata(
        tenant_id=payload.tenant_id,
        organization_name=payload.organization_name,
        seats=payload.seats,
        used_seats=used_seats,
        plan_type=payload.plan_type,
        issued_at=payload.issued_at,
        expires_at=payload.expires_at,
        grace_period_end=grace_period_end,
        status=status.value,
        source=source,
        stripe_subscription_id=payload.stripe_subscription_id,
    )

    redis_client.setex(
        LICENSE_METADATA_KEY,
        LICENSE_CACHE_TTL_SECONDS,
        metadata.model_dump_json(),
    )

    logger.info(f"License cache updated: {metadata.seats} seats, status={status.value}")
    return metadata


def refresh_license_cache(
    db_session: Session,
    tenant_id: str | None = None,
) -> LicenseMetadata | None:
    """
    Refresh the license cache from the database.

    Args:
        db_session: Database session
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        LicenseMetadata if license exists, None otherwise
    """
    from ee.onyx.utils.license import verify_license_signature

    license_record = get_license(db_session)
    if not license_record:
        invalidate_license_cache(tenant_id)
        return None

    try:
        payload = verify_license_signature(license_record.license_data)
        return update_license_cache(
            payload,
            source=LicenseSource.AUTO_FETCH,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        logger.error(f"Failed to verify license during cache refresh: {e}")
        invalidate_license_cache(tenant_id)
        return None


def get_license_metadata(
    db_session: Session,
    tenant_id: str | None = None,
) -> LicenseMetadata | None:
    """
    Get license metadata, using cache if available.

    Args:
        db_session: Database session
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        LicenseMetadata if license exists, None otherwise
    """
    # Try cache first
    cached = get_cached_license_metadata(tenant_id)
    if cached:
        return cached

    # Refresh from database
    return refresh_license_cache(db_session, tenant_id)
