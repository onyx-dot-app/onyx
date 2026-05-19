"""Database and cache operations for the license table."""

import hashlib
import struct
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from ee.onyx.server.license.models import LicenseMetadata
from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import LicenseSource
from onyx.auth.schemas import UserRole
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import ANONYMOUS_USER_EMAIL
from onyx.db.enums import AccountType
from onyx.db.models import License
from onyx.db.models import User
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

LICENSE_METADATA_KEY = "license:metadata"
LICENSE_CACHE_TTL_SECONDS = 86400  # 24 hours

# Namespaced + tenant-hashed so unrelated tenants don't block each other
# and the lock id can't collide with other advisory locks in the codebase.
_SEAT_LOCK_NAMESPACE = "onyx_seat_lock"


def seat_lock_id_for_tenant(tenant_id: str) -> int:
    digest = hashlib.sha256(f"{_SEAT_LOCK_NAMESPACE}:{tenant_id}".encode()).digest()
    # pg_advisory_xact_lock takes a signed 8-byte int.
    return struct.unpack("q", digest[:8])[0]


def acquire_seat_lock(db_session: Session, tenant_id: str | None = None) -> None:
    """Tenant-scoped advisory lock; released on the caller's commit/rollback.

    Caller must run the seat check AND the seat-consuming write in the
    same transaction.
    """
    lock_id = seat_lock_id_for_tenant(tenant_id or get_current_tenant_id())
    db_session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": lock_id},
    )


class SeatAvailabilityResult(NamedTuple):
    """Result of a seat availability check."""

    available: bool
    error_message: str | None = None


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


def user_counts_toward_seats(user: User) -> bool:
    """Per-user predicate matching ``get_used_seats``'s SQL filter below.

    Self-hosted only — cloud counts ``UserTenantMapping`` rows instead.
    Keep in sync with ``get_used_seats``.
    """
    return (
        bool(user.is_active)
        and user.role != UserRole.EXT_PERM_USER
        and user.email != ANONYMOUS_USER_EMAIL
        and user.account_type != AccountType.SERVICE_ACCOUNT
    )


def get_used_seats(tenant_id: str | None = None) -> int:
    """
    Get current seat usage directly from database.

    Multi-tenant: counts active UserTenantMapping rows. Self-hosted:
    counts active users excluding SERVICE_ACCOUNT, EXT_PERM_USER, and
    the anonymous user. BOT is counted (real humans).

    Per-user predicate ``user_counts_toward_seats`` mirrors this filter.
    """
    if MULTI_TENANT:
        from ee.onyx.server.tenants.user_mapping import get_tenant_count

        return get_tenant_count(tenant_id or get_current_tenant_id())
    else:
        from onyx.db.engine.sql_engine import get_session_with_current_tenant

        with get_session_with_current_tenant() as db_session:
            result = db_session.execute(
                select(func.count())
                .select_from(User)
                .where(
                    User.is_active == True,  # noqa: E712
                    User.role != UserRole.EXT_PERM_USER,
                    User.email != ANONYMOUS_USER_EMAIL,
                    User.account_type != AccountType.SERVICE_ACCOUNT,
                )
            )
            return result.scalar() or 0


# -----------------------------------------------------------------------------
# Redis Cache Operations
# -----------------------------------------------------------------------------


def get_cached_license_metadata(tenant_id: str | None = None) -> LicenseMetadata | None:
    """
    Get license metadata from cache.

    Args:
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        LicenseMetadata if cached, None otherwise
    """
    cache = get_cache_backend(tenant_id=tenant_id)
    cached = cache.get(LICENSE_METADATA_KEY)
    if not cached:
        return None

    try:
        cached_str = (
            cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
        )
        return LicenseMetadata.model_validate_json(cached_str)
    except Exception as e:
        logger.warning("Failed to parse cached license metadata: %s", e)
        return None


def invalidate_license_cache(tenant_id: str | None = None) -> None:
    """
    Invalidate the license metadata cache (not the license itself).

    Deletes the cached LicenseMetadata. The actual license in the database
    is not affected. Delete is idempotent — if the key doesn't exist, this
    is a no-op.

    Args:
        tenant_id: Tenant ID (for multi-tenant deployments)
    """
    cache = get_cache_backend(tenant_id=tenant_id)
    cache.delete(LICENSE_METADATA_KEY)
    logger.info("License cache invalidated")


def update_license_cache(
    payload: LicensePayload,
    source: LicenseSource | None = None,
    grace_period_end: datetime | None = None,
    tenant_id: str | None = None,
) -> LicenseMetadata:
    """
    Update the cache with license metadata.

    We cache all license statuses (ACTIVE, GRACE_PERIOD, GATED_ACCESS) because:
    1. Frontend needs status to show appropriate UI/banners
    2. Caching avoids repeated DB + crypto verification on every request
    3. Status enforcement happens at the feature level, not here

    Args:
        payload: Verified license payload
        source: How the license was obtained
        grace_period_end: Optional grace period end time
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        The cached LicenseMetadata
    """
    from ee.onyx.utils.license import get_license_status
    from ee.onyx.utils.license_expiry import get_expiry_warning_stage
    from ee.onyx.utils.license_expiry import get_grace_period_end

    tenant = tenant_id or get_current_tenant_id()
    cache = get_cache_backend(tenant_id=tenant_id)

    used_seats = get_used_seats(tenant)
    # Default the grace window to 14 days past expires_at so the license-
    # enforcement middleware returns GRACE_PERIOD (not GATED_ACCESS) during
    # that window — matching the banner copy and daily admin emails.
    effective_grace_end = grace_period_end or get_grace_period_end(payload.expires_at)
    status = get_license_status(payload, effective_grace_end)
    warning_stage = get_expiry_warning_stage(payload.expires_at)

    metadata = LicenseMetadata(
        tenant_id=payload.tenant_id,
        organization_name=payload.organization_name,
        seats=payload.seats,
        used_seats=used_seats,
        plan_type=payload.plan_type,
        issued_at=payload.issued_at,
        expires_at=payload.expires_at,
        grace_period_end=effective_grace_end,
        status=status,
        expiry_warning_stage=warning_stage,
        source=source,
        stripe_subscription_id=payload.stripe_subscription_id,
        customer_tier=payload.customer_tier,
    )

    cache.set(
        LICENSE_METADATA_KEY,
        metadata.model_dump_json(),
        ex=LICENSE_CACHE_TTL_SECONDS,
    )

    logger.info(
        "License cache updated: %s seats, status=%s", metadata.seats, status.value
    )
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
        # Derive source from payload: manual licenses lack stripe_customer_id
        source: LicenseSource = (
            LicenseSource.AUTO_FETCH
            if payload.stripe_customer_id
            else LicenseSource.MANUAL_UPLOAD
        )
        return update_license_cache(
            payload,
            source=source,
            tenant_id=tenant_id,
        )
    except ValueError as e:
        logger.error("Failed to verify license during cache refresh: %s", e)
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


def check_seat_availability(
    db_session: Session,
    seats_needed: int = 1,
    tenant_id: str | None = None,
) -> SeatAvailabilityResult:
    """
    Check if there are enough seats available to add users.

    Args:
        db_session: Database session
        seats_needed: Number of seats needed (default 1)
        tenant_id: Tenant ID (for multi-tenant deployments)

    Returns:
        SeatAvailabilityResult with available=True if seats are available,
        or available=False with error_message if limit would be exceeded.
        Returns available=True if no license exists (self-hosted = unlimited).
    """
    metadata = get_license_metadata(db_session, tenant_id)

    # No license = no enforcement (self-hosted without license)
    if metadata is None:
        return SeatAvailabilityResult(available=True)

    # Calculate current usage directly from DB (not cache) for accuracy
    current_used = get_used_seats(tenant_id)
    total_seats = metadata.seats

    # Use > (not >=) to allow filling to exactly 100% capacity
    would_exceed_limit = current_used + seats_needed > total_seats
    if would_exceed_limit:
        return SeatAvailabilityResult(
            available=False,
            error_message=f"Seat limit would be exceeded: {current_used} of {total_seats} seats used, "
            f"cannot add {seats_needed} more user(s).",
        )

    return SeatAvailabilityResult(available=True)
